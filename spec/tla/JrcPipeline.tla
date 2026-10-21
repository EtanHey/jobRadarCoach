---------------------------- MODULE JrcPipeline ----------------------------
EXTENDS Integers, FiniteSets
CONSTANT CurrentCode
Boards == {"comeet", "lever", "workable"}
Postings == 1..4
MaxAge == 1
FreshFor == 1
Horizon == 2
VARIABLES fixture, registryCase, phase, now, eligible, fetched, geo, matched,
          processed, representative, receipt, latest, checkedAt, historical, closed, priorClosed
vars == <<fixture, registryCase, phase, now, eligible, fetched, geo, matched,
          processed, representative, receipt, latest, checkedAt, historical, closed, priorClosed>>

Source(p) == CASE p <= 2 -> "comeet" [] p = 3 -> "lever" [] OTHER -> "workable"
ExternalId(p) == p
Employer(p) == IF p = 4 THEN "OtherCo" ELSE "Employer"
Requisition(p) == IF p <= 2 THEN (IF fixture = "jd" THEN "" ELSE IF p = 2 /\ fixture = "distinct" THEN "R2" ELSE "R1")
                  ELSE IF p = 3 THEN "R2" ELSE "R3"
JdGroup(p) == IF p = 4 THEN "foreign" ELSE IF p = 3 /\ fixture = "jd"
             THEN "other-jd" ELSE "shared-jd"
Location(p) == IF p = 4 THEN "London" ELSE IF p <= 2 /\ fixture = "city"
              THEN (IF p = 1 THEN "Tel Aviv-Yafo" ELSE "Herzliya")
              ELSE IF p <= 2 /\ fixture = "location"
              THEN (IF p = 1 THEN "Tel Aviv, Israel" ELSE "Haifa, Israel") ELSE "Israel"
Title(p) == IF p = 3 THEN "Analyst" ELSE IF p = 2 /\ fixture \in {"title", "jd", "role"}
            THEN "Updated Engineer" ELSE "Engineer"
RoleKey(p) == IF p = 2 /\ fixture \in {"role", "location"} THEN 1 ELSE ExternalId(p)
TitleMatches(p) == p # 4
Deadline(p) == IF p <= 2 THEN 1 ELSE Horizon + 1
Enabled(b) == ~(registryCase = "disabled" /\ b = "workable")
VerifiedAge(b) == IF registryCase = "stale" /\ b = "lever" THEN MaxAge + 1 ELSE MaxAge
BoardPostings(b, ps) == {p \in ps : Source(p) = b}
GeoPass(p) == Location(p) \in {"Israel", "Tel Aviv, Israel", "Haifa, Israel"} \/
             (~CurrentCode /\ Location(p) \in {"Tel Aviv-Yafo", "Herzliya"})
SameVacancy(p, q) == Employer(p) = Employer(q) /\
    IF Requisition(p) # "" /\ Requisition(q) # ""
    THEN Requisition(p) = Requisition(q)
    ELSE Requisition(p) = "" /\ Requisition(q) = "" /\ JdGroup(p) = JdGroup(q)
SameStoredRow(p, q) == Source(p) = Source(q) /\ ExternalId(p) = ExternalId(q)
Stored == {representative[p] : p \in processed}
Min(ps) == CHOOSE p \in ps : \A q \in ps : p <= q
UiSameRole(p, q) == Employer(p) = Employer(q) /\
    (Location(p) = Location(q) \/ "Israel" \in {Location(p), Location(q)}) /\
    (RoleKey(p) = RoleKey(q) \/ Title(p) = Title(q))
RECURSIVE UiGroups(_)
UiGroups(ps) == IF ps = {} THEN {} ELSE
    LET p == CHOOSE x \in ps : \A y \in ps : x >= y
        groups == UiGroups(ps \ {p})
        peers == {g \in groups : \A q \in g : UiSameRole(p, q)}
        first == CHOOSE g \in peers : \A h \in peers : Min(g) <= Min(h)
    IN IF peers = {} THEN groups \cup {{p}}
       ELSE (groups \ {first}) \cup {first \cup {p}}
VisibleGroups == IF CurrentCode THEN UiGroups(Stored)
                 ELSE {{q \in processed : representative[q] = r} : r \in Stored}
Visible == {Min(g) : g \in VisibleGroups}
Fresh(p) == latest[p] = "success" /\ checkedAt[p] >= 0 /\
            now - checkedAt[p] <= FreshFor /\ now <= Deadline(p)
DisplayedAlive == {p \in Visible : IF CurrentCode THEN historical[p] ELSE Fresh(p)}

Init == /\ fixture \in {"city", "requisition", "distinct", "title", "location", "jd", "role"}
        /\ registryCase \in {"fresh", "stale", "disabled"}
        /\ phase = "registry" /\ now = 0
        /\ eligible = {} /\ fetched = {} /\ geo = {} /\ matched = {}
        /\ processed = {} /\ representative = [p \in Postings |-> 0]
        /\ LET absent == IF CurrentCode THEN -1 ELSE 0
           IN receipt = [b \in Boards |-> [registered |-> IF CurrentCode THEN -1 ELSE 1,
                eligible |-> absent, requested |-> absent, fetched |-> absent, matched |-> absent,
                filtered |-> absent, inserted |-> absent, warnings |-> {}]]
        /\ latest = [p \in Postings |-> "none"]
        /\ checkedAt = [p \in Postings |-> -1]
        /\ historical = [p \in Postings |-> FALSE] /\ closed = {}
        /\ priorClosed = [p \in Postings |-> FALSE]

Registry ==
    /\ phase = "registry"
    /\ LET qs == {b \in Boards : Enabled(b) /\ VerifiedAge(b) <= MaxAge}
       IN /\ eligible' = qs
          /\ receipt' = [b \in Boards |-> [receipt[b] EXCEPT
               !.eligible = IF CurrentCode THEN @ ELSE IF b \in qs THEN 1 ELSE 0,
               !.warnings = IF CurrentCode \/ b \in qs THEN {}
                 ELSE {IF Enabled(b) THEN "stale" ELSE "disabled"}]]
    /\ phase' = "fetch"
    /\ UNCHANGED <<fixture, registryCase, now, fetched, geo, matched, processed,
                   representative, latest, checkedAt, historical, closed, priorClosed>>
Fetch ==
    /\ phase = "fetch"
    /\ \E ok \in SUBSET eligible:
         /\ fetched' = {p \in Postings : Source(p) \in ok}
         /\ receipt' = [b \in Boards |-> [receipt[b] EXCEPT
              !.requested = IF CurrentCode THEN @ ELSE IF b \in eligible THEN 1 ELSE 0,
              !.fetched = Cardinality(BoardPostings(b, fetched')),
              !.warnings = @ \cup (IF b \in eligible \ ok THEN {"fetch-failed"} ELSE {})]]
    /\ phase' = "filter"
    /\ UNCHANGED <<fixture, registryCase, now, eligible, geo, matched, processed,
                   representative, latest, checkedAt, historical, closed, priorClosed>>
Filter ==
    /\ phase = "filter"
    /\ geo' = {p \in fetched : GeoPass(p)}
    /\ matched' = {p \in geo' : TitleMatches(p)}
    /\ receipt' = [b \in Boards |-> [receipt[b] EXCEPT
         !.matched = Cardinality(BoardPostings(b, matched')),
         !.filtered = IF CurrentCode THEN @ ELSE Cardinality(BoardPostings(b, fetched \ matched')),
         !.warnings = @ \cup (IF ~CurrentCode /\ BoardPostings(b, fetched) # {} /\
              BoardPostings(b, matched') = {} THEN {"all-filtered"} ELSE {})]]
    /\ phase' = "upsert"
    /\ UNCHANGED <<fixture, registryCase, now, eligible, fetched, processed,
                   representative, latest, checkedAt, historical, closed, priorClosed>>
Upsert ==
    /\ phase = "upsert" /\ processed # matched
    /\ \E p \in matched \ processed:
         LET peers == {q \in Stored : IF CurrentCode THEN SameStoredRow(p, q)
                                       ELSE SameVacancy(p, q)}
             rep == IF peers = {} THEN p ELSE CHOOSE q \in peers : TRUE
         IN /\ processed' = processed \cup {p}
            /\ representative' = [representative EXCEPT ![p] = rep]
            /\ receipt' = [receipt EXCEPT ![Source(p)].inserted = IF CurrentCode THEN @ ELSE @ + 1]
    /\ UNCHANGED <<fixture, registryCase, phase, now, eligible, fetched, geo, matched,
                   latest, checkedAt, historical, closed, priorClosed>>
Finish == /\ phase = "upsert" /\ processed = matched /\ phase' = "live"
          /\ UNCHANGED <<fixture, registryCase, now, eligible, fetched, geo, matched,
               processed, representative, receipt, latest, checkedAt, historical, closed, priorClosed>>
Check ==
    /\ phase = "live"
    /\ \E p \in Visible, result \in {"success", "unknown", "dead"}:
         /\ checkedAt[p] < now
         /\ latest' = [latest EXCEPT ![p] = result]
         /\ checkedAt' = [checkedAt EXCEPT ![p] = now]
         /\ historical' = [historical EXCEPT ![p] =
              IF result = "unknown" THEN @ ELSE result = "success"]
         /\ priorClosed' = [priorClosed EXCEPT ![p] = p \in closed]
         /\ closed' = IF result = "dead" THEN closed \cup {p}
                      ELSE IF result = "success" THEN closed \ {p} ELSE closed
    /\ UNCHANGED <<fixture, registryCase, phase, now, eligible, fetched, geo, matched,
                   processed, representative, receipt>>
Tick == /\ phase = "live" /\ now < Horizon /\ now' = now + 1
        /\ UNCHANGED <<fixture, registryCase, phase, eligible, fetched, geo, matched,
             processed, representative, receipt, latest, checkedAt, historical, closed, priorClosed>>
Next == Registry \/ Fetch \/ Filter \/ Upsert \/ Finish \/ Check \/ Tick
Spec == Init /\ [][Next]_vars
\* Witness constraints select initial fixtures, never prune changing pipeline state.
StaleWitness == registryCase = "stale"
GeoWitness == registryCase = "fresh" /\ fixture = "city"
RequisitionWitness == fixture = "requisition"
JdWitness == fixture = "jd"
DistinctWitness == fixture = "distinct"
TitleWitness == fixture = "title"
LocationWitness == fixture = "location"
RoleWitness == fixture = "role"

NoSilentSourceLoss ==
    /\ (phase # "registry" => \A b \in Boards :
          b \notin eligible => receipt[b].warnings # {} \/
            (receipt[b].registered = 1 /\ receipt[b].eligible = 0))
    /\ (phase \in {"upsert", "live"} => \A b \in Boards :
          (BoardPostings(b, fetched) # {} /\ BoardPostings(b, matched) = {})
            => "all-filtered" \in receipt[b].warnings \/
              (receipt[b].fetched > 0 /\ receipt[b].matched = 0))
OneVisibleVacancy ==
    /\ \A p \in processed : \E g \in VisibleGroups : p \in g
    /\ \A p, q \in processed :
          (\E g \in VisibleGroups : p \in g /\ q \in g) <=> SameVacancy(p, q)
AliveImpliesFreshCheck ==
    /\ \A p \in DisplayedAlive : Fresh(p)
    /\ \A p \in Visible : latest[p] = "unknown" =>
          (p \in closed <=> priorClosed[p])
LocationAcceptsCityOnly == phase \in {"upsert", "live"} =>
    \A p \in fetched : (p \in geo <=> Location(p) \in {"Israel", "Tel Aviv-Yafo", "Herzliya",
                                                                    "Tel Aviv, Israel", "Haifa, Israel"})
=============================================================================
