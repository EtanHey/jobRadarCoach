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
        "Raanana",
        "Modiin",
        "Modi'in",
        "Hod Hasharon",
        "Netanya",
        "Rehovot",
        "Kfar Saba",
        "Holon",
        "Rishon",
        "Rishon LeZion",
        "Rishon Le Zion",
        "Ramat HaSharon",
        "Lod",
        "Rosh HaAyin",
        "Nes Ziona",
        "Bnei Brak",
        "Yehud Monosson",
        "Beer Yaakov",
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
        "מודיעין",
        "הוד השרון",
        "נתניה",
        "רחובות",
        "כפר סבא",
        "חולון",
        "ראשון לציון",
        "באר שבע",
        "יקנעם",
    ),
    "united states": (
        "San Francisco",
        "New York",
        "New York City",
        "Austin",
        "NYC",
        "SF",
    ),
    "germany": ("Berlin",),
    "united kingdom": ("London", "לונדון"),
    "canada": ("Toronto",),
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
# Hebrew ISO 3166-1 names from Unicode CLDR 48.0.0; data only.
# https://raw.githubusercontent.com/unicode-org/cldr-json/48.0.0/cldr-json/cldr-localenames-full/main/he/territories.json
HEBREW_COUNTRY_NAMES = {
    "AD": "אנדורה",
    "AE": "איחוד האמירויות הערביות",
    "AF": "אפגניסטן",
    "AG": "אנטיגואה וברבודה",
    "AI": "אנגווילה",
    "AL": "אלבניה",
    "AM": "ארמניה",
    "AO": "אנגולה",
    "AQ": "אנטארקטיקה",
    "AR": "ארגנטינה",
    "AS": "סמואה האמריקנית",
    "AT": "אוסטריה",
    "AU": "אוסטרליה",
    "AW": "ארובה",
    "AX": "איי אולנד",
    "AZ": "אזרבייג׳ן",
    "BA": "בוסניה והרצגובינה",
    "BB": "ברבדוס",
    "BD": "בנגלדש",
    "BE": "בלגיה",
    "BF": "בורקינה פאסו",
    "BG": "בולגריה",
    "BH": "בחריין",
    "BI": "בורונדי",
    "BJ": "בנין",
    "BL": "סנט ברתולומיאו",
    "BM": "ברמודה",
    "BN": "ברוניי",
    "BO": "בוליביה",
    "BQ": "האיים הקריביים ההולנדיים",
    "BR": "ברזיל",
    "BS": "איי בהאמה",
    "BT": "בהוטן",
    "BV": "האי בובה",
    "BW": "בוטסואנה",
    "BY": "בלארוס",
    "BZ": "בליז",
    "CA": "קנדה",
    "CC": "איי קוקוס (קילינג)",
    "CD": "קונגו - קינשאסה",
    "CF": "הרפובליקה המרכז-אפריקאית",
    "CG": "קונגו - ברזאויל",
    "CH": "שווייץ",
    "CI": "חוף השנהב",
    "CK": "איי קוק",
    "CL": "צ׳ילה",
    "CM": "קמרון",
    "CN": "סין",
    "CO": "קולומביה",
    "CR": "קוסטה ריקה",
    "CU": "קובה",
    "CV": "כף ורדה",
    "CW": "קוראסאו",
    "CX": "אי חג המולד",
    "CY": "קפריסין",
    "CZ": "צ׳כיה",
    "DE": "גרמניה",
    "DJ": "ג׳יבוטי",
    "DK": "דנמרק",
    "DM": "דומיניקה",
    "DO": "הרפובליקה הדומיניקנית",
    "DZ": "אלג׳יריה",
    "EC": "אקוודור",
    "EE": "אסטוניה",
    "EG": "מצרים",
    "EH": "סהרה המערבית",
    "ER": "אריתריאה",
    "ES": "ספרד",
    "ET": "אתיופיה",
    "FI": "פינלנד",
    "FJ": "פיג׳י",
    "FK": "איי פוקלנד",
    "FM": "מיקרונזיה",
    "FO": "איי פארו",
    "FR": "צרפת",
    "GA": "גבון",
    "GB": "בריטניה",
    "GD": "גרנדה",
    "GE": "גאורגיה",
    "GF": "גיאנה הצרפתית",
    "GG": "גרנזי",
    "GH": "גאנה",
    "GI": "גיברלטר",
    "GL": "גרינלנד",
    "GM": "גמביה",
    "GN": "גינאה",
    "GP": "גוואדלופ",
    "GQ": "גינאה המשוונית",
    "GR": "יוון",
    "GS": "ג׳ורג׳יה הדרומית ואיי סנדוויץ׳ הדרומיים",
    "GT": "גואטמלה",
    "GU": "גואם",
    "GW": "גינאה-ביסאו",
    "GY": "גיאנה",
    "HK": "הונג קונג (אזור מנהלי מיוחד של סין)",
    "HM": "איי הרד ומקדונלד",
    "HN": "הונדורס",
    "HR": "קרואטיה",
    "HT": "האיטי",
    "HU": "הונגריה",
    "ID": "אינדונזיה",
    "IE": "אירלנד",
    "IL": "ישראל",
    "IM": "האי מאן",
    "IN": "הודו",
    "IO": "הטריטוריה הבריטית באוקיינוס ההודי",
    "IQ": "עיראק",
    "IR": "איראן",
    "IS": "איסלנד",
    "IT": "איטליה",
    "JE": "ג׳רזי",
    "JM": "ג׳מייקה",
    "JO": "ירדן",
    "JP": "יפן",
    "KE": "קניה",
    "KG": "קירגיזסטן",
    "KH": "קמבודיה",
    "KI": "קיריבאטי",
    "KM": "קומורו",
    "KN": "סנט קיטס ונוויס",
    "KP": "קוריאה הצפונית",
    "KR": "קוריאה הדרומית",
    "KW": "כווית",
    "KY": "איי קיימן",
    "KZ": "קזחסטן",
    "LA": "לאוס",
    "LB": "לבנון",
    "LC": "סנט לוסיה",
    "LI": "ליכטנשטיין",
    "LK": "סרי לנקה",
    "LR": "ליבריה",
    "LS": "לסוטו",
    "LT": "ליטא",
    "LU": "לוקסמבורג",
    "LV": "לטביה",
    "LY": "לוב",
    "MA": "מרוקו",
    "MC": "מונקו",
    "MD": "מולדובה",
    "ME": "מונטנגרו",
    "MF": "סן מרטן",
    "MG": "מדגסקר",
    "MH": "איי מרשל",
    "MK": "מקדוניה הצפונית",
    "ML": "מאלי",
    "MM": "מיאנמר (בורמה)",
    "MN": "מונגוליה",
    "MO": "מקאו (אזור מנהלי מיוחד של סין)",
    "MP": "איי מריאנה הצפוניים",
    "MQ": "מרטיניק",
    "MR": "מאוריטניה",
    "MS": "מונסראט",
    "MT": "מלטה",
    "MU": "מאוריציוס",
    "MV": "האיים המלדיביים",
    "MW": "מלאווי",
    "MX": "מקסיקו",
    "MY": "מלזיה",
    "MZ": "מוזמביק",
    "NA": "נמיביה",
    "NC": "קלדוניה החדשה",
    "NE": "ניז׳ר",
    "NF": "האי נורפוק",
    "NG": "ניגריה",
    "NI": "ניקרגואה",
    "NL": "הולנד",
    "NO": "נורווגיה",
    "NP": "נפאל",
    "NR": "נאורו",
    "NU": "ניווה",
    "NZ": "ניו זילנד",
    "OM": "עומאן",
    "PA": "פנמה",
    "PE": "פרו",
    "PF": "פולינזיה הצרפתית",
    "PG": "פפואה גינאה החדשה",
    "PH": "הפיליפינים",
    "PK": "פקיסטן",
    "PL": "פולין",
    "PM": "סנט פייר ומיקלון",
    "PN": "איי פיטקרן",
    "PR": "פוארטו ריקו",
    "PS": "השטחים הפלסטיניים",
    "PT": "פורטוגל",
    "PW": "פלאו",
    "PY": "פרגוואי",
    "QA": "קטאר",
    "RE": "ראוניון",
    "RO": "רומניה",
    "RS": "סרביה",
    "RU": "רוסיה",
    "RW": "רואנדה",
    "SA": "ערב הסעודית",
    "SB": "איי שלמה",
    "SC": "איי סיישל",
    "SD": "סודן",
    "SE": "שוודיה",
    "SG": "סינגפור",
    "SH": "סנט הלנה",
    "SI": "סלובניה",
    "SJ": "סבאלברד ויאן מאיין",
    "SK": "סלובקיה",
    "SL": "סיירה לאון",
    "SM": "סן מרינו",
    "SN": "סנגל",
    "SO": "סומליה",
    "SR": "סורינאם",
    "SS": "דרום סודן",
    "ST": "סאו טומה ופרינסיפה",
    "SV": "אל סלבדור",
    "SX": "סנט מארטן",
    "SY": "סוריה",
    "SZ": "אסוואטיני",
    "TC": "איי טרקס וקייקוס",
    "TD": "צ׳אד",
    "TF": "הטריטוריות הדרומיות של צרפת",
    "TG": "טוגו",
    "TH": "תאילנד",
    "TJ": "טג׳יקיסטן",
    "TK": "טוקלאו",
    "TL": "טימור-לסטה",
    "TM": "טורקמניסטן",
    "TN": "תוניסיה",
    "TO": "טונגה",
    "TR": "טורקיה",
    "TT": "טרינידד וטובגו",
    "TV": "טובאלו",
    "TW": "טייוואן",
    "TZ": "טנזניה",
    "UA": "אוקראינה",
    "UG": "אוגנדה",
    "UM": "האיים המרוחקים הקטנים של ארה״ב",
    "US": "ארצות הברית",
    "UY": "אורוגוואי",
    "UZ": "אוזבקיסטן",
    "VA": "הוותיקן",
    "VC": "סנט וינסנט והגרנדינים",
    "VE": "ונצואלה",
    "VG": "איי הבתולה הבריטיים",
    "VI": "איי הבתולה של ארצות הברית",
    "VN": "וייטנאם",
    "VU": "ונואטו",
    "WF": "איי ווליס ופוטונה",
    "WS": "סמואה",
    "YE": "תימן",
    "YT": "מאיוט",
    "ZA": "דרום אפריקה",
    "ZM": "זמביה",
    "ZW": "זימבבואה",
}
HEBREW_REGION_NAMES = (
    "אירופה",
    "האיחוד האירופי",
    "איחוד האירופי",
    "אמריקה הלטינית",
    "אסיה",
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
    "germany": frozenset(("germany", "de", "deu")),
    "united kingdom": frozenset(("united kingdom", "uk", "gb", "gbr")),
    "canada": frozenset(("canada", "ca", "can")),
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

# Eligibility uses this same vocabulary as ingestion, with explicit region policy.
# Unknown places are deliberately unresolved, never presumed foreign or Israeli.
NONCENTRAL_ISRAEL_PLACES = (
    "Sasa",
    "Kibbutz Sasa",
    "Galilee",
    "Upper Galilee",
    "Haifa",
    "Jerusalem",
    "Be'er Sheva",
    "Yokneam",
    "northern Israel",
    "southern Israel",
    "סאסא",
    "גליל",
    "חיפה",
    "ירושלים",
    "באר שבע",
    "יקנעם",
    "צפון",
    "דרום",
)
GEOGRAPHIC_ALIASES = {
    **{name: "foreign" for name in COUNTRY_IDENTIFIERS},
    **dict.fromkeys(HEBREW_COUNTRY_NAMES.values(), "foreign"),
    **dict.fromkeys(HEBREW_REGION_NAMES, "foreign"),
    **{city: "foreign" for cities in COUNTRY_CITY_ALIASES.values() for city in cities},
    **{city: "israel" for city in COUNTRY_CITY_ALIASES["israel"]},
    **{name: "noncentral" for name in NONCENTRAL_ISRAEL_PLACES},
    **dict.fromkeys(
        (
            "Israel",
            "State of Israel",
            "IL",
            "ISR",
            "ישראל",
            "Central Israel",
            "Gush Dan",
            "מרכז ישראל",
            "גוש דן",
        ),
        "israel",
    ),
    **dict.fromkeys(
        (
            "United States",
            "U.S.",
            "U.S.A.",
            "US",
            "USA",
            "Continental United States",
            "ארצות הברית",
            "ארה״ב",
            'ארה"ב',
            "ארהב",
            "קנדה",
            "בריטניה",
            "אירופה",
            "Europe",
            "European Union",
            "EU",
            "UK",
            "New Jersey",
        ),
        "foreign",
    ),
    **dict.fromkeys(("EMEA", "APAC", "EST", "PST"), "uncertain"),
    **dict.fromkeys(
        ("worldwide", "globally", "global", "anywhere in the world", "all countries"),
        "worldwide",
    ),
}
_PLACE_KINDS = {
    _normalized_location(name): kind for name, kind in GEOGRAPHIC_ALIASES.items()
}
_PLACE_PATTERN = re.compile(
    r"(?:"
    + "|".join(
        r"[\W_]+".join(map(re.escape, name.split()))
        for name in sorted(_PLACE_KINDS, key=len, reverse=True)
    )
    + r")(?!\w)",
    re.I,
)


def match_geographic_place(text: str, start: int = 0) -> tuple[str, int] | None:
    """Resolve one place at a geographic scope boundary, preserving unknowns.

    ISO codes need uppercase input (except conventional US/UK/EU); ordinary
    words such as 'in', 'it', 'be' must not become countries in prose.
    """
    match = _PLACE_PATTERN.match(text, start)
    if not match:
        return None
    name = _normalized_location(match.group())
    if (
        len(name) <= 3
        and name in COUNTRY_IDENTIFIERS
        and name not in {"us", "u s", "uk", "eu"}
    ):
        if not match.group().isupper():
            return None
    end = match.end()
    if name in {"u s", "u s a"} and text[end : end + 1] == ".":
        end += 1
    return _PLACE_KINDS[name], end


def has_geographic_context(text: str) -> bool:
    """Prose needs geographic meaning; ISO codes alone can be technical acronyms."""
    if re.search(
        r"\b(?:remote|reside|residents?|residence|residency|relocat\w*|"
        r"located (?:in|within)|based (?:in|worldwide)|office|on[ -]?site|citizens?(?:hip)?|passport|"
        r"work authorization|eligible to work|time[ -]?zone|country|countries|"
        r"jurisdiction|location|(?:candidates?|applicants?) (?:in|from))\b|"
        r"(?<!\w)(?:מגורים|תושבי\w*|להתגורר|לגור|מרחוק|בישראל|אזרחות|"
        r"[במ]?מדינ\w*|[במ]?אזור זמן)(?!\w)",
        text,
        re.I,
    ):
        return True
    for word in re.finditer(r"\b\w", text):
        place = match_geographic_place(text, word.start())
        if not place:
            # Hebrew prepositions/articles attach to country names. Only strip
            # a bounded Hebrew prefix, never letters inside an arbitrary word.
            for length in range(1, 4):
                prefix = text[word.start() : word.start() + length]
                start = word.start() + length
                if re.fullmatch(r"[בלמוהש]+", prefix) and match_geographic_place(
                    text, start
                ):
                    return True
            continue
        if place[0] == "worldwide":
            continue
        name = _normalized_location(text[word.start() : place[1]])
        if text[word.start() : place[1]].isupper() and re.match(
            r"(?:\s+|[ -]based\s+)(?:candidates?|applicants?|residents?|citizens?|"
            r"work\s+(?:permits?|authorization))\b",
            text[place[1] :],
            re.I,
        ):
            return True
        if name in {"ai", "ml", "sc", "it", "ci", "cd"}:
            continue
        if len(name) > 3 or re.search(r"[א-ת]", name) or place[0] == "uncertain":
            return True
        # 'AI', 'SC', 'IT', and pronoun 'us' are not place evidence in prose.
        if re.search(
            r"\b(?:in|from|within|across|to)\s+(?:the\s+)?$", text[: word.start()], re.I
        ):
            if name != "us" or text[word.start() : place[1]].isupper():
                return True
    return False


def normalize_israeli_location(text: str) -> str:
    """Consume known ATS district qualifiers without discarding other places."""
    text = re.sub(r"^\d+\s+Locations?,\s*(Israel)\s*$", r"\1", text, flags=re.I)
    text = re.sub(r"\band across Israel\b", "and Israel", text, flags=re.I)
    text = re.sub(r"\b(Gush Dan|Tel Aviv)\s+Area\b", r"\1", text, flags=re.I)
    return re.sub(
        r"\b(Tel Aviv|Center|Central|Haifa|Jerusalem|North|South)\s+District\b",
        lambda m: {
            "center": "Central Israel",
            "central": "Central Israel",
            "north": "northern Israel",
            "south": "southern Israel",
        }.get(m[1].casefold(), m[1]),
        text,
        flags=re.I,
    )


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
