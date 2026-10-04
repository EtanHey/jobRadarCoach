// Bounded identity hints, not geocoding. Unknown locations cannot prove exclusion.
const israelCities = [
  ["tel aviv", "tel aviv", "tel aviv|tel aviv yafo|tel aviv jaffa"],
  ["haifa", "haifa", "haifa"], ["jerusalem", "jerusalem", "jerusalem"],
  ["petah tikva", "center", "petah tikva|petach tikva|petah tiqwa"],
  ["ramat gan", "tel aviv", "ramat gan"], ["bnei brak", "tel aviv", "bnei brak"],
  ["raanana", "center", "raanana|ra anana"], ["kfar monash", "center", "kfar monash"],
  ["sarid", "north", "sarid"], ["ramat yishai", "north", "ramat yishai"],
  ["yokneam ilit", "north", "yokneam ilit|yokneam|yoqneam illit"],
];
const usCities = [
  ["charlotte", "nc"], ["wayne", "pa"], ["skippack", "pa"], ["herndon", "va"],
  ["seattle", "wa"], ["chicago", "il"], ["lisle", "il"], ["rochester hills", "mi"],
  ["hialeah", "fl"], ["jersey city", "nj"], ["redmond", "wa"], ["bastrop", "tx"],
  ["austin", "tx"], ["san francisco", "ca"], ["new york", "ny"], ["stamford", "ct"],
];
const states = Object.fromEntries([
  ["minnesota", "mn"], ["illinois", "il"], ["alabama", "al"], ["georgia", "ga"],
  ["pennsylvania", "pa"], ["texas", "tx"], ["california", "ca"], ["maryland", "md"],
  ["michigan", "mi"], ["new york", "ny"], ["washington", "wa"], ["north carolina", "nc"],
  ["virginia", "va"], ["florida", "fl"], ["colorado", "co"],
]);
const stateCodes = "al ak az ar ca co ct de dc fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy".split(" ");
const countries = [
  ["israel", "israel"], ["us", "united states|usa|us"], ["canada", "canada"],
  ["uk", "united kingdom|uk|england"], ["france", "france"], ["germany", "germany"],
  ["netherlands", "netherlands"], ["poland", "poland"], ["australia", "australia"],
  ..."india|china|japan|singapore|brazil|mexico|spain|italy|sweden|denmark|finland|norway|greece|portugal|switzerland|austria|new zealand|south africa".split("|").map(key => [key, key]),
];
function normalize(value: string): string {
  return value.normalize("NFKC").toLowerCase().replace(/\([^)]*\)/gu, "")
    .replace(/[.’']/gu, "").replace(/[-–/|]/gu, " ").replace(/\s+/gu, " ").trim();
}
type LocationFacts = { text: string; country: string[]; city: string | null; region: string | null };
function israelHints(result: LocationFacts, first: string) {
  for (const [key, area, aliases] of israelCities) {
    if (aliases.split("|").includes(first)) { result.city = key; result.region = area; if (!result.country.length) result.country.push("israel"); }
  }
  for (const area of ["tel aviv", "haifa", "jerusalem", "center", "north", "south"]) {
    if (result.text.includes(`${area} district`)) { result.region = area; if (!result.country.length) result.country.push("israel"); }
  }
}
function usHints(result: LocationFacts, parts: string[]) {
  if (result.country.length === 0) {
    for (const [key, area] of usCities) {
      if (parts[0] === key && !result.country.length) { result.city = key; result.region = area; result.country.push("us"); }
    }
  }
  const namedStates = Object.keys(states).filter(name => new RegExp(`(?:^|[ ,])${name}(?:$|[ ,])`, "u").test(result.text));
  if (namedStates.length && !result.country.length) result.country.push("us");
  if (result.country.length === 1 && result.country[0] === "us") {
    const codes = [...new Set(parts.map(part => part.replace(/^or /u, "")).filter(part => stateCodes.includes(part)))];
    const areas = [...new Set([...codes, ...namedStates.map(name => states[name])])];
    if (areas.length === 1) result.region = areas[0];
  }
}
function facts(value: string | null): LocationFacts {
  const text = normalize(value ?? ""), parts = text.split(",").map(part => part.trim()), first = parts[0];
  const country = countries.filter(([, aliases]) => new RegExp(`(?:^|[ ,])(?:${aliases})(?:$|[ ,])`, "u").test(text)).map(([key]) => key);
  const result: LocationFacts = { text, country, city: null, region: null };
  israelHints(result, first);
  usHints(result, parts);
  if (country.length === 1 && !result.city && parts.length > 1 && !countries.some(([, aliases]) => aliases.split("|").includes(first))
    && !states[first] && !/district|region|remote|central|customer/gu.test(first)) result.city = first;
  return result;
}
export function compatibleRepostLocations(a: string | null, b: string | null): boolean {
  const left = facts(a), right = facts(b);
  if (left.text === right.text) return true;
  if (left.country.length && right.country.length && !left.country.some(country => right.country.includes(country))) return false;
  if (left.region && right.region && left.region !== right.region) return false;
  return !left.city || !right.city || left.city === right.city;
}
