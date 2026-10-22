"""Shared country/city recognition for ingestion and local eligibility."""

import re


def _contains_normalized_phrase(text: str, phrase: str) -> bool:
    text_tokens = text.split()
    phrase_tokens = phrase.split()
    return bool(phrase_tokens) and any(
        text_tokens[index : index + len(phrase_tokens)] == phrase_tokens
        for index in range(len(text_tokens))
    )


# Code-owned country scope for city-only ATS locations. Profile aliases are additive.
COUNTRY_CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "israel": (
        "Tel Aviv",
        "Tel Aviv-Yafo",
        "Herzliya",
        "Ramat Gan",
        "Petah Tikva",
        "Haifa",
        "Jerusalem",
        "Ra'anana",
        "Hod Hasharon",
        "Netanya",
        "Rehovot",
        "Kfar Saba",
        "Be'er Sheva",
        "Yokneam",
        "תל אביב",
        "תל אביב-יפו",
        "הרצליה",
        "רמת גן",
        "פתח תקווה",
        "חיפה",
        "ירושלים",
        "רעננה",
        "הוד השרון",
        "נתניה",
        "רחובות",
        "כפר סבא",
        "באר שבע",
        "יקנעם",
    ),
    "united states": ("San Francisco",),
}


def _normalized_location(value: object) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", str(value).casefold()).split())


# Generated from pycountry 24.6.1 (ISO 3166-1); data only, no runtime dependency.
COUNTRY_IDENTIFIERS = frozenset(
    _normalized_location(identifier)
    for identifier in (
        "AD|AND|Andorra|Principality of Andorra|"
        "AE|ARE|United Arab Emirates|"
        "AF|AFG|Afghanistan|Islamic Republic of Afghanistan|"
        "AG|ATG|Antigua and Barbuda|"
        "AI|AIA|Anguilla|"
        "AL|ALB|Albania|Republic of Albania|"
        "AM|ARM|Armenia|Republic of Armenia|"
        "AO|AGO|Angola|Republic of Angola|"
        "AQ|ATA|Antarctica|"
        "AR|ARG|Argentina|Argentine Republic|"
        "AS|ASM|American Samoa|"
        "AT|AUT|Austria|Republic of Austria|"
        "AU|AUS|Australia|"
        "AW|ABW|Aruba|"
        "AX|ALA|Åland Islands|"
        "AZ|AZE|Azerbaijan|Republic of Azerbaijan|"
        "BA|BIH|Bosnia and Herzegovina|Republic of Bosnia and Herzegovina|"
        "BB|BRB|Barbados|"
        "BD|BGD|Bangladesh|People's Republic of Bangladesh|"
        "BE|BEL|Belgium|Kingdom of Belgium|"
        "BF|BFA|Burkina Faso|"
        "BG|BGR|Bulgaria|Republic of Bulgaria|"
        "BH|BHR|Bahrain|Kingdom of Bahrain|"
        "BI|BDI|Burundi|Republic of Burundi|"
        "BJ|BEN|Benin|Republic of Benin|"
        "BL|BLM|Saint Barthélemy|"
        "BM|BMU|Bermuda|"
        "BN|BRN|Brunei Darussalam|"
        "BO|BOL|Bolivia, Plurinational State of|Plurinational State of Bolivia|Bolivia|"
        "BQ|BES|Bonaire, Sint Eustatius and Saba|"
        "BR|BRA|Brazil|Federative Republic of Brazil|"
        "BS|BHS|Bahamas|Commonwealth of the Bahamas|"
        "BT|BTN|Bhutan|Kingdom of Bhutan|"
        "BV|BVT|Bouvet Island|"
        "BW|BWA|Botswana|Republic of Botswana|"
        "BY|BLR|Belarus|Republic of Belarus|"
        "BZ|BLZ|Belize|"
        "CA|CAN|Canada|"
        "CC|CCK|Cocos (Keeling) Islands|"
        "CD|COD|Congo, The Democratic Republic of the|"
        "CF|CAF|Central African Republic|"
        "CG|COG|Congo|Republic of the Congo|"
        "CH|CHE|Switzerland|Swiss Confederation|"
        "CI|CIV|Côte d'Ivoire|Republic of Côte d'Ivoire|"
        "CK|COK|Cook Islands|"
        "CL|CHL|Chile|Republic of Chile|"
        "CM|CMR|Cameroon|Republic of Cameroon|"
        "CN|CHN|China|People's Republic of China|"
        "CO|COL|Colombia|Republic of Colombia|"
        "CR|CRI|Costa Rica|Republic of Costa Rica|"
        "CU|CUB|Cuba|Republic of Cuba|"
        "CV|CPV|Cabo Verde|Republic of Cabo Verde|"
        "CW|CUW|Curaçao|"
        "CX|CXR|Christmas Island|"
        "CY|CYP|Cyprus|Republic of Cyprus|"
        "CZ|CZE|Czechia|Czech Republic|"
        "DE|DEU|Germany|Federal Republic of Germany|"
        "DJ|DJI|Djibouti|Republic of Djibouti|"
        "DK|DNK|Denmark|Kingdom of Denmark|"
        "DM|DMA|Dominica|Commonwealth of Dominica|"
        "DO|DOM|Dominican Republic|"
        "DZ|DZA|Algeria|People's Democratic Republic of Algeria|"
        "EC|ECU|Ecuador|Republic of Ecuador|"
        "EE|EST|Estonia|Republic of Estonia|"
        "EG|EGY|Egypt|Arab Republic of Egypt|"
        "EH|ESH|Western Sahara|"
        "ER|ERI|Eritrea|the State of Eritrea|"
        "ES|ESP|Spain|Kingdom of Spain|"
        "ET|ETH|Ethiopia|Federal Democratic Republic of Ethiopia|"
        "FI|FIN|Finland|Republic of Finland|"
        "FJ|FJI|Fiji|Republic of Fiji|"
        "FK|FLK|Falkland Islands (Malvinas)|"
        "FM|FSM|Micronesia, Federated States of|Federated States of Micronesia|"
        "FO|FRO|Faroe Islands|"
        "FR|FRA|France|French Republic|"
        "GA|GAB|Gabon|Gabonese Republic|"
        "GB|GBR|United Kingdom|United Kingdom of Great Britain and Northern Ireland|"
        "GD|GRD|Grenada|"
        "GE|GEO|Georgia|"
        "GF|GUF|French Guiana|"
        "GG|GGY|Guernsey|"
        "GH|GHA|Ghana|Republic of Ghana|"
        "GI|GIB|Gibraltar|"
        "GL|GRL|Greenland|"
        "GM|GMB|Gambia|Republic of the Gambia|"
        "GN|GIN|Guinea|Republic of Guinea|"
        "GP|GLP|Guadeloupe|"
        "GQ|GNQ|Equatorial Guinea|Republic of Equatorial Guinea|"
        "GR|GRC|Greece|Hellenic Republic|"
        "GS|SGS|South Georgia and the South Sandwich Islands|"
        "GT|GTM|Guatemala|Republic of Guatemala|"
        "GU|GUM|Guam|"
        "GW|GNB|Guinea-Bissau|Republic of Guinea-Bissau|"
        "GY|GUY|Guyana|Republic of Guyana|"
        "HK|HKG|Hong Kong|Hong Kong Special Administrative Region of China|"
        "HM|HMD|Heard Island and McDonald Islands|"
        "HN|HND|Honduras|Republic of Honduras|"
        "HR|HRV|Croatia|Republic of Croatia|"
        "HT|HTI|Haiti|Republic of Haiti|"
        "HU|HUN|Hungary|"
        "ID|IDN|Indonesia|Republic of Indonesia|"
        "IE|IRL|Ireland|"
        "IL|ISR|Israel|State of Israel|"
        "IM|IMN|Isle of Man|"
        "IN|IND|India|Republic of India|"
        "IO|IOT|British Indian Ocean Territory|"
        "IQ|IRQ|Iraq|Republic of Iraq|"
        "IR|IRN|Iran, Islamic Republic of|Islamic Republic of Iran|Iran|"
        "IS|ISL|Iceland|Republic of Iceland|"
        "IT|ITA|Italy|Italian Republic|"
        "JE|JEY|Jersey|"
        "JM|JAM|Jamaica|"
        "JO|JOR|Jordan|Hashemite Kingdom of Jordan|"
        "JP|JPN|Japan|"
        "KE|KEN|Kenya|Republic of Kenya|"
        "KG|KGZ|Kyrgyzstan|Kyrgyz Republic|"
        "KH|KHM|Cambodia|Kingdom of Cambodia|"
        "KI|KIR|Kiribati|Republic of Kiribati|"
        "KM|COM|Comoros|Union of the Comoros|"
        "KN|KNA|Saint Kitts and Nevis|"
        "KP|PRK|Korea, Democratic People's Republic of|Democratic People's Republic of Korea|North Korea|"
        "KR|KOR|Korea, Republic of|South Korea|"
        "KW|KWT|Kuwait|State of Kuwait|"
        "KY|CYM|Cayman Islands|"
        "KZ|KAZ|Kazakhstan|Republic of Kazakhstan|"
        "LA|LAO|Lao People's Democratic Republic|Laos|"
        "LB|LBN|Lebanon|Lebanese Republic|"
        "LC|LCA|Saint Lucia|"
        "LI|LIE|Liechtenstein|Principality of Liechtenstein|"
        "LK|LKA|Sri Lanka|Democratic Socialist Republic of Sri Lanka|"
        "LR|LBR|Liberia|Republic of Liberia|"
        "LS|LSO|Lesotho|Kingdom of Lesotho|"
        "LT|LTU|Lithuania|Republic of Lithuania|"
        "LU|LUX|Luxembourg|Grand Duchy of Luxembourg|"
        "LV|LVA|Latvia|Republic of Latvia|"
        "LY|LBY|Libya|"
        "MA|MAR|Morocco|Kingdom of Morocco|"
        "MC|MCO|Monaco|Principality of Monaco|"
        "MD|MDA|Moldova, Republic of|Republic of Moldova|Moldova|"
        "ME|MNE|Montenegro|"
        "MF|MAF|Saint Martin (French part)|"
        "MG|MDG|Madagascar|Republic of Madagascar|"
        "MH|MHL|Marshall Islands|Republic of the Marshall Islands|"
        "MK|MKD|North Macedonia|Republic of North Macedonia|"
        "ML|MLI|Mali|Republic of Mali|"
        "MM|MMR|Myanmar|Republic of Myanmar|"
        "MN|MNG|Mongolia|"
        "MO|MAC|Macao|Macao Special Administrative Region of China|"
        "MP|MNP|Northern Mariana Islands|Commonwealth of the Northern Mariana Islands|"
        "MQ|MTQ|Martinique|"
        "MR|MRT|Mauritania|Islamic Republic of Mauritania|"
        "MS|MSR|Montserrat|"
        "MT|MLT|Malta|Republic of Malta|"
        "MU|MUS|Mauritius|Republic of Mauritius|"
        "MV|MDV|Maldives|Republic of Maldives|"
        "MW|MWI|Malawi|Republic of Malawi|"
        "MX|MEX|Mexico|United Mexican States|"
        "MY|MYS|Malaysia|"
        "MZ|MOZ|Mozambique|Republic of Mozambique|"
        "NA|NAM|Namibia|Republic of Namibia|"
        "NC|NCL|New Caledonia|"
        "NE|NER|Niger|Republic of the Niger|"
        "NF|NFK|Norfolk Island|"
        "NG|NGA|Nigeria|Federal Republic of Nigeria|"
        "NI|NIC|Nicaragua|Republic of Nicaragua|"
        "NL|NLD|Netherlands|Kingdom of the Netherlands|"
        "NO|NOR|Norway|Kingdom of Norway|"
        "NP|NPL|Nepal|Federal Democratic Republic of Nepal|"
        "NR|NRU|Nauru|Republic of Nauru|"
        "NU|NIU|Niue|"
        "NZ|NZL|New Zealand|"
        "OM|OMN|Oman|Sultanate of Oman|"
        "PA|PAN|Panama|Republic of Panama|"
        "PE|PER|Peru|Republic of Peru|"
        "PF|PYF|French Polynesia|"
        "PG|PNG|Papua New Guinea|Independent State of Papua New Guinea|"
        "PH|PHL|Philippines|Republic of the Philippines|"
        "PK|PAK|Pakistan|Islamic Republic of Pakistan|"
        "PL|POL|Poland|Republic of Poland|"
        "PM|SPM|Saint Pierre and Miquelon|"
        "PN|PCN|Pitcairn|"
        "PR|PRI|Puerto Rico|"
        "PS|PSE|Palestine, State of|the State of Palestine|"
        "PT|PRT|Portugal|Portuguese Republic|"
        "PW|PLW|Palau|Republic of Palau|"
        "PY|PRY|Paraguay|Republic of Paraguay|"
        "QA|QAT|Qatar|State of Qatar|"
        "RE|REU|Réunion|"
        "RO|ROU|Romania|"
        "RS|SRB|Serbia|Republic of Serbia|"
        "RU|RUS|Russian Federation|"
        "RW|RWA|Rwanda|Rwandese Republic|"
        "SA|SAU|Saudi Arabia|Kingdom of Saudi Arabia|"
        "SB|SLB|Solomon Islands|"
        "SC|SYC|Seychelles|Republic of Seychelles|"
        "SD|SDN|Sudan|Republic of the Sudan|"
        "SE|SWE|Sweden|Kingdom of Sweden|"
        "SG|SGP|Singapore|Republic of Singapore|"
        "SH|SHN|Saint Helena, Ascension and Tristan da Cunha|"
        "SI|SVN|Slovenia|Republic of Slovenia|"
        "SJ|SJM|Svalbard and Jan Mayen|"
        "SK|SVK|Slovakia|Slovak Republic|"
        "SL|SLE|Sierra Leone|Republic of Sierra Leone|"
        "SM|SMR|San Marino|Republic of San Marino|"
        "SN|SEN|Senegal|Republic of Senegal|"
        "SO|SOM|Somalia|Federal Republic of Somalia|"
        "SR|SUR|Suriname|Republic of Suriname|"
        "SS|SSD|South Sudan|Republic of South Sudan|"
        "ST|STP|Sao Tome and Principe|Democratic Republic of Sao Tome and Principe|"
        "SV|SLV|El Salvador|Republic of El Salvador|"
        "SX|SXM|Sint Maarten (Dutch part)|"
        "SY|SYR|Syrian Arab Republic|Syria|"
        "SZ|SWZ|Eswatini|Kingdom of Eswatini|"
        "TC|TCA|Turks and Caicos Islands|"
        "TD|TCD|Chad|Republic of Chad|"
        "TF|ATF|French Southern Territories|"
        "TG|TGO|Togo|Togolese Republic|"
        "TH|THA|Thailand|Kingdom of Thailand|"
        "TJ|TJK|Tajikistan|Republic of Tajikistan|"
        "TK|TKL|Tokelau|"
        "TL|TLS|Timor-Leste|Democratic Republic of Timor-Leste|"
        "TM|TKM|Turkmenistan|"
        "TN|TUN|Tunisia|Republic of Tunisia|"
        "TO|TON|Tonga|Kingdom of Tonga|"
        "TR|TUR|Türkiye|Republic of Türkiye|"
        "TT|TTO|Trinidad and Tobago|Republic of Trinidad and Tobago|"
        "TV|TUV|Tuvalu|"
        "TW|TWN|Taiwan, Province of China|Taiwan|"
        "TZ|TZA|Tanzania, United Republic of|United Republic of Tanzania|Tanzania|"
        "UA|UKR|Ukraine|"
        "UG|UGA|Uganda|Republic of Uganda|"
        "UM|UMI|United States Minor Outlying Islands|"
        "US|USA|United States|United States of America|"
        "UY|URY|Uruguay|Eastern Republic of Uruguay|"
        "UZ|UZB|Uzbekistan|Republic of Uzbekistan|"
        "VA|VAT|Holy See (Vatican City State)|"
        "VC|VCT|Saint Vincent and the Grenadines|"
        "VE|VEN|Venezuela, Bolivarian Republic of|Bolivarian Republic of Venezuela|Venezuela|"
        "VG|VGB|Virgin Islands, British|British Virgin Islands|"
        "VI|VIR|Virgin Islands, U.S.|Virgin Islands of the United States|"
        "VN|VNM|Viet Nam|Socialist Republic of Viet Nam|Vietnam|"
        "VU|VUT|Vanuatu|Republic of Vanuatu|"
        "WF|WLF|Wallis and Futuna|"
        "WS|WSM|Samoa|Independent State of Samoa|"
        "YE|YEM|Yemen|Republic of Yemen|"
        "YT|MYT|Mayotte|"
        "ZA|ZAF|South Africa|Republic of South Africa|"
        "ZM|ZMB|Zambia|Republic of Zambia|"
        "ZW|ZWE|Zimbabwe|Republic of Zimbabwe|"
        "UK|United Kingdom|Great Britain|Britain|U.S.|U.S.A.|Russia|South Korea|"
        "North Korea|Taiwan|Vietnam|Bolivia|Venezuela|Iran|Syria|Laos|Moldova|"
        "Tanzania|Brunei|Palestine|Czech Republic|Turkey|Cape Verde|Ivory Coast"
    ).split("|")
    if identifier
)
US_STATE_IDENTIFIERS = frozenset(
    _normalized_location(identifier)
    for identifier in (
        "AL|Alabama|AK|Alaska|AZ|Arizona|AR|Arkansas|CA|California|CO|Colorado|"
        "CT|Connecticut|DE|Delaware|FL|Florida|GA|Georgia|HI|Hawaii|ID|Idaho|"
        "IL|Illinois|IN|Indiana|IA|Iowa|KS|Kansas|KY|Kentucky|LA|Louisiana|"
        "ME|Maine|MD|Maryland|MA|Massachusetts|MI|Michigan|MN|Minnesota|"
        "MS|Mississippi|MO|Missouri|MT|Montana|NE|Nebraska|NV|Nevada|"
        "NH|New Hampshire|NJ|New Jersey|NM|New Mexico|NY|New York|"
        "NC|North Carolina|ND|North Dakota|OH|Ohio|OK|Oklahoma|OR|Oregon|"
        "PA|Pennsylvania|RI|Rhode Island|SC|South Carolina|SD|South Dakota|"
        "TN|Tennessee|TX|Texas|UT|Utah|VT|Vermont|VA|Virginia|WA|Washington|"
        "WV|West Virginia|WI|Wisconsin|WY|Wyoming|DC|District of Columbia"
    ).split("|")
)
COUNTRY_OWN_IDENTIFIERS = {
    "israel": frozenset(("israel", "il", "isr")),
    "united states": frozenset(
        (
            "united states",
            "united states of america",
            "us",
            "usa",
            "u s",
            "u s a",
        )
    ),
}


def _city_matches_country(raw_location: object, country: str) -> bool:
    cities = COUNTRY_CITY_ALIASES.get(country, ())
    if not cities:
        return False
    segments = [
        normalized
        for part in re.split(r"[,;|/\n()]|\s+[-–—]\s+", str(raw_location))
        if (normalized := _normalized_location(part))
    ]
    city_names = {_normalized_location(city) for city in cities}
    city_indices = {
        index for index, segment in enumerate(segments) if segment in city_names
    }
    if not city_indices:
        return False
    own_identifiers = COUNTRY_OWN_IDENTIFIERS[country]
    for index, segment in enumerate(segments):
        if segment in own_identifiers:
            continue
        # CA (Canada/California), IL (Israel/Illinois), etc. are ambiguous. Only
        # the segment immediately after a US city is interpreted as a US state.
        if (
            country == "united states"
            and index - 1 in city_indices
            and segment in US_STATE_IDENTIFIERS
        ):
            continue
        if segment in COUNTRY_IDENTIFIERS or (
            country != "united states" and segment in US_STATE_IDENTIFIERS
        ):
            return False
    return True
