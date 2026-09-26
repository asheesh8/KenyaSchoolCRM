"""Kenya Schools Directory: a database of every school in Kenya and a light CRM for reaching them.

Harvester steps (python3 -m harvest <step>):
  areas     counties and constituencies with populations (HDX/OCHA, KNBS 2019 census, WorldPop)
  moe       Ministry of Education school list (every registered school, with level and sponsor)
  osm       OpenStreetMap schools: phones, emails, websites, head teachers, enrolment
  wikidata  official websites for well-known schools
  dedupe    fold duplicate records together
  discover  find school websites (.sc.ke / .ac.ke domains, optional Brave Search API)
  crawl     read each school's website for emails, phones, addresses and the principal's name
  places    optional, paid: Google Places phone numbers and websites
"""
