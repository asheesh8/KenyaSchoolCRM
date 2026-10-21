# Uganda raw research record schema (one JSON object per line, file raw/<worker>.jsonl)

Same as Sierra Leone's, adapted to Uganda and the shared Africa CRM format (/mnt/project-files/africa-crm/DATA-FORMAT.md).

{
 "name": "official name as published",
 "kind": "school" | "office" | "secretariat" | "association" | "ngo",
 "levels": ["pre_primary","primary","lower_secondary","upper_secondary","tvet","tertiary","admin"],
 "region": "Central" | "Eastern" | "Northern" | "Western" | null,
 "district": one of the canonical district names below (as spelled), or null,
 "area": county / sub-county / division if shown, else null,
 "town": null, "address": null,
 "ownership": "government" | "government_assisted" | "private" | "community" | "mission" | "ngo" | "unknown",
 "denomination": null or e.g. "Catholic","Anglican","Islamic","SDA","Pentecostal","Orthodox","Baptist",
 "website": null,
 "emails":   [{"email": "...", "source_url": "...", "confidence": "high|medium|low", "seen": "year or date the page shows, else null"}],
 "phones":   [{"phone": "+256 7XX XXX XXX", "source_url": "..."}],
 "officials":[{"name": "...", "role": "Head Teacher|Headmaster|Headmistress|Principal|Director|Proprietor|Deputy Head Teacher|Vice Chancellor|Academic Registrar|District Education Officer|Inspector of Schools|Education Secretary|...", "email": null, "phone": null, "source_url": "..."}],
 "emis_code": null (EMIS number or UNEB centre number, e.g. "U0001"), "lat": null, "lon": null,
 "students": null (enrolment, if published),
 "sources": ["every URL used"],
 "notes": null,
 "worker": "<worker slug>"
}

Levels: pre_primary = nursery (baby/middle/top class); primary = P1-P7; lower_secondary = O-level S1-S4;
upper_secondary = A-level S5-S6 (a full "S1-S6" secondary school gets both); tvet = BTVET, technical
institutes, vocational centres; tertiary = universities, colleges, PTCs/NTCs, nursing/health institutes;
admin = district education offices, foundation bodies, diocesan education secretariats, ministry units.

Canonical districts (region):
Central: Buikwe, Bukomansimbi, Butambala, Buvuma, Gomba, Kalangala, Kalungu, Kampala, Kassanda, Kayunga, Kiboga, Kyankwanzi, Kyotera, Luwero, Lwengo, Lyantonde, Masaka, Mityana, Mpigi, Mubende, Mukono, Nakaseke, Nakasongola, Rakai, Ssembabule, Wakiso
Eastern: Amuria, Budaka, Bududa, Bugiri, Bugweri, Bukedea, Bukwo, Bulambuli, Busia, Butaleja, Butebo, Buyende, Iganga, Jinja, Kaberamaido, Kalaki, Kaliro, Kamuli, Kapchorwa, Kapelebyong, Katakwi, Kibuku, Kumi, Kween, Luuka, Manafwa, Mayuge, Mbale, Namayingo, Namisindwa, Namutumba, Ngora, Pallisa, Serere, Sironko, Soroti, Tororo
Northern: Abim, Adjumani, Agago, Alebtong, Amolatar, Amudat, Amuru, Apac, Arua, Dokolo, Gulu, Kaabong, Karenga, Kitgum, Koboko, Kole, Kotido, Kwania, Lamwo, Lira, Madi Okollo, Maracha, Moroto, Moyo, Nabilatuk, Nakapiripirit, Napak, Nebbi, Nwoya, Obongi, Omoro, Otuke, Oyam, Pader, Pakwach, Terego, Yumbe, Zombo
Western: Buhweju, Buliisa, Bundibugyo, Bunyangabu, Bushenyi, Hoima, Ibanda, Isingiro, Kabale, Kabarole, Kagadi, Kakumiro, Kamwenge, Kanungu, Kasese, Kazo, Kibaale, Kikuube, Kiruhura, Kiryandongo, Kisoro, Kitagwenda, Kyegegwa, Kyenjojo, Masindi, Mbarara, Mitooma, Ntoroko, Ntungamo, Rubanda, Rubirizi, Rukiga, Rukungiri, Rwampara, Sheema
(Cities such as Gulu City, Mbarara City, Fort Portal (= Kabarole), Entebbe (= Wakiso), Mbale City go under their district.)

Confidence: high = shown on the institution's own site or an official government/church page dated 2020 or later;
medium = third-party directory, news article, or official page dated 2015-2019 or undated;
low = older than 2015, or the page is ambiguous about whose address it is.
Never guess, construct or pattern-fill an email address. Every email, phone and official must appear verbatim on its source_url.
Personal emails/phones are fine only when the page publishes them as the school's or the official's work contact.
