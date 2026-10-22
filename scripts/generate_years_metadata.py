"""Generate SQL and replay the shared precision-first grammar without database access."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "ui/lib/experience-patterns.json").read_text())
NUMBER = SPEC['number']
LEAD = rf"(?<![A-Za-z0-9_.])(?:(?:at least|minimum(?:[ \t]+of)?|over)[ \t]+)?{NUMBER}(?:[ \t]*(?:[-–—]|to)[ \t]*{NUMBER})?\+?[ \t]+(?:overall[ \t]+)?years?\b"
FRAME = '|'.join([LEAD + tail for tail in SPEC['englishTail']] + [SPEC['hebrew']])
RANGE = rf'{NUMBER}[ \t]*[-–—][ \t]*{NUMBER}'


def search(pattern, text):
    return re.search(pattern, text, re.I | re.ASCII)


def normalize(description):
    text = description.translate(str.maketrans({**dict.fromkeys(SPEC['normalization']['space'], ' '),
                                               **dict.fromkeys(SPEC['normalization']['newline'], '\n')}))
    for pattern in SPEC['normalization']['mask']:
        text = re.sub(pattern, lambda m: ' ' * len(m[0]), text, flags=re.I | re.M | re.ASCII)
    return text


def experience_phrase(description):
    """Offline reference for the TS and generated SQL decision sequence."""
    if not description:
        return None
    text = normalize(description)
    if search(SPEC['fractionalTenure'], text) or re.search(SPEC['numberedTenure'], text, re.I | re.M | re.ASCII):
        return None
    selected, disagreement = None, False
    for clause_match in re.finditer(r'[^.!?;\n]+', text):
        clause = clause_match[0]
        if not search(SPEC['tenure'], clause):
            continue
        section = 'other'
        for heading in re.finditer(SPEC['headings'], text[:clause_match.start()], re.I | re.M | re.ASCII):
            heading_text = next(g for g in heading.groups() if g is not None)
            heading_text = re.sub(r'^[^A-Za-zא-ת]+', '', re.sub(r'[:#*]+$', '', heading_text)).strip()
            if not re.search(r'[.!?;]', heading_text) and search(SPEC['optionalScope'], heading_text) and not search(SPEC['headingTenure'].replace('{number}', NUMBER), heading_text):
                section = 'optional'
            elif search(SPEC['requiredHeading'], heading_text):
                section = 'applicant'
            elif search(SPEC['otherHeading'], heading_text):
                section = 'other'
        if search(SPEC['inlineRequiredHeading'], clause):
            section = 'applicant'
        if section == 'optional' or search(SPEC['company'], clause):
            continue
        matches = list(re.finditer(FRAME, clause, re.I | re.ASCII))
        residue = clause[:matches[0].start()] + clause[matches[0].end():] if len(matches) == 1 else clause
        if search(SPEC['complexity'], residue) or search(SPEC['optionalScope'], clause):
            return None
        if section != 'applicant' and not search(SPEC['requiredContext'], clause):
            continue
        if search(SPEC['reject'], residue) or search(SPEC['extraNumber'], residue) or len(matches) != 1 or search(SPEC['tenure'], residue):
            return None
        match = matches[0]
        if (search(SPEC['complexity'], re.sub(RANGE, '', match[0], count=1, flags=re.I | re.ASCII))
                or search(SPEC['extraNumber'], re.sub(SPEC['quantity'], '', match[0], count=1, flags=re.I | re.ASCII))):
            return None
        tokens = re.findall(rf'(?<![A-Za-z0-9_]){NUMBER}(?![A-Za-z0-9_])', match[0], re.I | re.ASCII)
        amounts = [int(token) if token.isdigit() else SPEC['words'].index(token.lower()) for token in tokens]
        if not amounts or (len(amounts) > 1 and amounts[1] < amounts[0]):
            return None
        quote = re.sub(r'^minimum(?:[ \t]+of)?[ \t]+', '', match[0], flags=re.I | re.ASCII)
        start = clause_match.start() + match.end() - len(quote)
        rank = int(section == 'applicant')
        if selected is None or rank > selected[2]:
            selected, disagreement = (amounts[0], description[start:start + len(quote)], rank), False
        elif rank == selected[2] and amounts[0] != selected[0]:
            disagreement = True
    return None if disagreement or selected is None else selected[1]


def sql_regex(pattern):
    boundary = r"(?:(?<![A-Za-z0-9_])(?=[A-Za-z0-9_])|(?<=[A-Za-z0-9_])(?![A-Za-z0-9_]))"
    whitespace = "[" + "".join(r"\u%04x" % ord(char) for key in ("space", "newline")
                                  for char in SPEC["normalization"][key]) + "]"
    return pattern.replace(r"\b", boundary).replace(r"\w", "A-Za-z0-9_").replace(r"\s", whitespace).replace("'", "''")


def generate():
    original = (ROOT / 'supabase/migrations/0024_list_metadata.sql').read_text()
    technologies = original[original.index('  select coalesce(array_agg'):original.index('  loop\n')]
    available = original.split("'description_available',coalesce((description collate \"C\") ~ '")[1].split("',false)")[0]
    translations = []
    for key, target in (('space', ' '), ('newline', '\n')):
        chars = ' || '.join(f'chr({ord(char)})' for char in SPEC['normalization'][key])
        translations.append(f"  normalized := translate(normalized, {chars}, repeat(chr({ord(target)}), {len(SPEC['normalization'][key])}));")
    normalization = '\n'.join(translations)
    masks = ','.join("'" + sql_regex(pattern) + "'" for pattern in SPEC['normalization']['mask'])
    patterns = {key: sql_regex(value) for key, value in SPEC.items() if isinstance(value, str)}
    return f"""-- GENERATED by scripts/generate_years_metadata.py; edit the shared grammar first.
-- Updates future description writes. Existing cached rows need an operator-owned backfill.
begin;
create or replace function public.posting_list_metadata(description text)
returns jsonb language plpgsql immutable security invoker set search_path = '' as $fn$
declare
  technologies text[];
  normalized text := coalesce(description,'');
  mask_pattern text; mask_start integer; mask_end integer;
  position integer; clause_start integer; clause_end integer; clause text;
  captures text[]; heading text; section text;
  start_at integer; end_at integer; matched text; residue text; quoted text;
  amounts integer[]; rank integer; selected_rank integer := -1;
  selected_minimum integer; disagreement boolean := false;
  experience text := null;
begin
{technologies}{normalization}
  -- Preserve source offsets, including every shared Unicode whitespace character.
  foreach mask_pattern in array array[{masks}] loop
    position := 1;
    loop
      mask_start := regexp_instr(normalized collate "C", mask_pattern, position, 1, 0, 'in');
      exit when mask_start = 0;
      mask_end := regexp_instr(normalized collate "C", mask_pattern, position, 1, 1, 'in');
      normalized := overlay(normalized placing repeat(' ',mask_end-mask_start) from mask_start for mask_end-mask_start);
      position := mask_end;
    end loop;
  end loop;
  -- A numbered/lettered tenure list is never interpreted as independent minima.
  if (normalized collate "C") !~* '{patterns['fractionalTenure']}' and (normalized collate "C") !~* '(?n){patterns['numberedTenure']}' then
    position := 1;
    loop
      clause_start := regexp_instr(normalized, '[^.!?;\\n]+', position);
      exit when clause_start = 0;
      clause_end := regexp_instr(normalized, '[^.!?;\\n]+', position, 1, 1);
      position := clause_end;
      clause := substr(normalized,clause_start,clause_end-clause_start);
      if (clause collate "C") !~* '{patterns['tenure']}' then continue; end if;
      section := 'other';
      for captures in select regexp_matches(substr(normalized,1,clause_start-1) collate "C",'{patterns['headings']}','gin') loop
        heading := btrim(regexp_replace(regexp_replace(coalesce(captures[1],captures[2],captures[3]),'[:#*]+$',''),'^[^A-Za-zא-ת]+',''));
        if heading !~ '[.!?;]' and (heading collate "C") ~* '{patterns['optionalScope']}' and (heading collate "C") !~* '{sql_regex(SPEC['headingTenure'].replace('{number}', NUMBER))}' then section := 'optional';
        elsif (heading collate "C") ~* '{patterns['requiredHeading']}' then section := 'applicant';
        elsif (heading collate "C") ~* '{patterns['otherHeading']}' then section := 'other'; end if;
      end loop;
      if (clause collate "C") ~* '{patterns['inlineRequiredHeading']}' then section := 'applicant'; end if;
      if section = 'optional' or (clause collate "C") ~* '{patterns['company']}' then continue; end if;
      start_at := regexp_instr(clause collate "C", '{sql_regex(FRAME)}', 1, 1, 0, 'i');
      end_at := regexp_instr(clause collate "C", '{sql_regex(FRAME)}', 1, 1, 1, 'i');
      -- PostgreSQL ARE chooses a longest alternative; English ends at the first experience.
      if start_at > 0 and substr(clause,start_at,1) !~ '[א-ת]' and substr(clause,start_at,end_at-start_at) !~ '[א-ת]' then
        end_at := regexp_instr(clause collate "C", '(?<![A-Za-z0-9_])experience(?![A-Za-z0-9_])', start_at, 1, 1, 'i');
      end if;
      matched := substr(clause,start_at,end_at-start_at);
      residue := clause;
      if start_at > 0 and regexp_instr(clause collate "C", '{sql_regex(FRAME)}', end_at, 1, 0, 'i') = 0 then
        residue := substr(clause,1,start_at-1) || substr(clause,end_at);
      end if;
      if (residue collate "C") ~* '{patterns['complexity']}' or (clause collate "C") ~* '{patterns['optionalScope']}' then experience := null; exit; end if;
      if section <> 'applicant' and (clause collate "C") !~* '{patterns['requiredContext']}' then continue; end if;
      if (residue collate "C") ~* '{patterns['reject']}' or (residue collate "C") ~* '{patterns['extraNumber']}' or start_at = 0 or (residue collate "C") ~* '{patterns['tenure']}'
        or (regexp_replace(matched collate "C", '{sql_regex(RANGE)}','','i') collate "C") ~* '{patterns['complexity']}'
        or (regexp_replace(matched collate "C", '{patterns['quantity']}','','i') collate "C") ~* '{patterns['extraNumber']}' then experience := null; exit; end if;
      select array_agg(case when m[1] ~ '^[0-9]+$' then m[1]::integer
        else array_position(array{SPEC['words']}::text[],lower(m[1])) - 1 end)
        into amounts from regexp_matches(matched collate "C", '(?<![A-Za-z0-9_])({patterns['number']})(?![A-Za-z0-9_])','gi') m;
      if amounts[1] is null or (array_length(amounts,1) > 1 and amounts[2] < amounts[1]) then experience := null; exit; end if;
      quoted := regexp_replace(matched collate "C", '^minimum(?:[ \\t]+of)?[ \\t]+','','i');
      rank := case when section = 'applicant' then 1 else 0 end;
      if rank > selected_rank then
        selected_rank := rank; selected_minimum := amounts[1]; disagreement := false;
        experience := substr(description,clause_start + end_at - length(quoted) - 1,length(quoted));
      elsif rank = selected_rank and amounts[1] <> selected_minimum then disagreement := true; end if;
    end loop;
  end if;
  if disagreement then experience := null; end if;
  return jsonb_build_object('stack',technologies,'experience',experience,
    'description_available',coalesce((description collate "C") ~ '{available}',false));
end
$fn$;
revoke all on function public.posting_list_metadata(text) from public, anon, authenticated;
grant execute on function public.posting_list_metadata(text) to service_role;
commit;
"""


if __name__ == '__main__':
    (ROOT / 'supabase/migrations/0039_years_metadata.sql').write_text(generate())
