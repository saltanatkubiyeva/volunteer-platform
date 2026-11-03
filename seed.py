"""Creates instance/demeu.db and fills it with realistic demo data.

Dates are generated relative to *today*, so the demo always has past events
(with confirmed hours and reviews) and upcoming events (with open registration).

    python seed.py          # create the database if it does not exist
    python seed.py --reset  # delete and recreate it
"""
import json
import os
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DEMEU_DB") or os.path.join(BASE, "instance", "demeu.db")
SCHEMA = os.path.join(BASE, "demeu", "schema.sql")
PASSWORD = "Demeu2026!"
rnd = random.Random(2026)
NOW = datetime.now().replace(second=0, microsecond=0)
FMT = "%Y-%m-%d %H:%M"

CITIES = [  # en, ru, kk, region, lat, lng
    ("Astana", "Астана", "Астана", "Astana city", 51.1694, 71.4491),
    ("Almaty", "Алматы", "Алматы", "Almaty city", 43.2389, 76.8897),
    ("Shymkent", "Шымкент", "Шымкент", "Shymkent city", 42.3417, 69.5901),
    ("Karaganda", "Караганда", "Қарағанды", "Karaganda region", 49.8047, 73.1094),
    ("Aktobe", "Актобе", "Ақтөбе", "Aktobe region", 50.2839, 57.1670),
    ("Uralsk", "Уральск", "Орал", "West Kazakhstan region", 51.2333, 51.3667),
    ("Kostanay", "Костанай", "Қостанай", "Kostanay region", 53.2144, 63.6246),
    ("Pavlodar", "Павлодар", "Павлодар", "Pavlodar region", 52.2873, 76.9674),
    ("Ust-Kamenogorsk", "Усть-Каменогорск", "Өскемен", "East Kazakhstan region", 49.9483, 82.6275),
    ("Atyrau", "Атырау", "Атырау", "Atyrau region", 47.0945, 51.9238),
    ("Turkestan", "Туркестан", "Түркістан", "Turkestan region", 43.2973, 68.2517),
]
C = {c[0]: i + 1 for i, c in enumerate(CITIES)}

DIRECTIONS = [  # slug, en, ru, kk, icon, tone
    ("ecology", "Ecology & Nature", "Экология и природа", "Экология және табиғат", "leaf", "mint"),
    ("animals", "Animal Welfare", "Помощь животным", "Жануарларға көмек", "paw", "butter"),
    ("children", "Children & Youth", "Дети и молодёжь", "Балалар мен жастар", "smile", "sky"),
    ("seniors", "Senior Care", "Помощь пожилым", "Қарттарға қамқорлық", "heart", "rose"),
    ("education", "Education & Mentoring", "Образование и наставничество", "Білім және тәлімгерлік", "graduation", "lilac"),
    ("social", "Social Aid", "Социальная помощь", "Әлеуметтік көмек", "package", "sage"),
    ("culture", "Culture & Events", "Культура и мероприятия", "Мәдениет және іс-шаралар", "palette", "lilac"),
    ("health", "Health & Donation", "Здоровье и донорство", "Денсаулық және донорлық", "heart-pulse", "rose"),
    ("sport", "Sport Events", "Спортивные события", "Спорт іс-шаралары", "trophy", "sky"),
    ("emergency", "Emergency Response", "ЧС и спасение", "Төтенше жағдайларға көмек", "lifebuoy", "butter"),
    ("digital", "Digital Help", "Цифровая помощь", "Цифрлық көмек", "laptop", "mint"),
]
D = {d[0]: i + 1 for i, d in enumerate(DIRECTIONS)}

# name, bin, type, city, address, email, phone, website, founded, status, directions, description
ORGS = [
    ("Green Steppe", "180940011223", "ngo", "Astana", "Kabanbay Batyr Ave 11, office 304", "hello@greensteppe.kz",
     "+77172556677", "https://greensteppe.kz", 2018, "verified", ["ecology", "education"],
     "Green Steppe restores city parks and riverbanks in Astana and teaches schoolchildren how to sort waste. "
     "We run weekly clean-ups, tree planting in spring and autumn, and eco-lessons in partner schools."),
    ("Paws of Almaty", "190540022334", "foundation", "Almaty", "Talgar highway 7 km, shelter territory",
     "info@pawsalmaty.kz", "+77272334455", "https://pawsalmaty.kz", 2019, "verified", ["animals"],
     "A private shelter for 300 dogs and 120 cats near Almaty. Volunteers walk and socialise animals, help at "
     "adoption days and repair enclosures. Every animal is vaccinated and sterilised before adoption."),
    ("Bilim Bridge", "200340033445", "initiative", "Shymkent", "Tauke Khan Ave 30, Youth Center",
     "team@bilimbridge.kz", "+77252445566", None, 2020, "verified", ["education", "digital", "children"],
     "Bilim Bridge brings free tutoring and digital-literacy classes to children from low-income families and "
     "to older people in Shymkent. Volunteers teach maths, English and basic computer skills."),
    ("Qamqorlyq Care", "170240044556", "foundation", "Karaganda", "Bukhar Zhyrau Ave 49",
     "care@qamqorlyq.kz", "+77212556600", "https://qamqorlyq.kz", 2017, "verified", ["seniors", "social"],
     "We support lonely elderly people in Karaganda: home visits, grocery delivery, help with paperwork and "
     "holiday concerts in care homes. Each volunteer gets a short training before the first visit."),
    ("Jaiyq River Keepers", "210140055667", "initiative", "Uralsk", "Dostyk Ave 182",
     "river@jaiyqkeepers.kz", "+77112667788", None, 2021, "verified", ["ecology"],
     "Citizens of Uralsk who keep the Ural (Jaiyq) river coast clean. We organise shoreline clean-ups, "
     "plant willows to stop erosion and measure water quality together with local students."),
    ("Steppe University Volunteer Club", "150840066778", "university", "Astana", "Mangilik El Ave 55/11, block C1",
     "volunteers@steppe-uni.kz", "+77172778899", "https://steppe-uni.kz/volunteers", 2015, "verified",
     ["children", "culture", "sport", "education"],
     "The student volunteer club of Steppe University. We help at city festivals and sports events, run a "
     "mentoring programme for orphanage graduates and organise charity fairs on campus."),
    ("Kind Hands Kostanay", "160640077889", "ngo", "Kostanay", "Al-Farabi Ave 115",
     "help@kindhands.kz", "+77142889900", None, 2016, "verified", ["social", "health", "seniors"],
     "Kind Hands collects and distributes food and clothing to families in need in Kostanay region and "
     "organises blood donation days together with the regional blood centre."),
    ("Almaty Run Crew", "220440088990", "initiative", "Almaty", "Al-Farabi Ave 77/8",
     "crew@almatyrun.kz", "+77273990011", "https://almatyrun.kz", 2022, "verified", ["sport", "culture"],
     "We recruit and train course marshals, water-station teams and finish-line volunteers for city runs "
     "and cycling events in Almaty. Free event T-shirt and meal for every volunteer."),
    ("Altai Rescue Volunteers", "190740099001", "ngo", "Ust-Kamenogorsk", "Kazakhstan St 64",
     "rescue@altairescue.kz", "+77232100200", None, 2019, "verified", ["emergency", "ecology"],
     "A volunteer search-and-rescue team in East Kazakhstan. We help during spring floods, search for missing "
     "people in the mountains together with the emergency services and teach first aid."),
    ("Pavlodar Food Share", "230940010112", "initiative", "Pavlodar", "Toraighyrov St 64",
     "foodshare.pvl@mail.kz", "+77182300400", None, 2023, "pending", ["social"],
     "We collect unsold but safe food from bakeries and shops in Pavlodar and deliver it to two shelters "
     "and to families registered with the city social service."),
    ("Quick Help KZ", "000000000001", "business", "Atyrau", "Satpayev Ave 1",
     "quickhelp@inbox.kz", "+77122000000", None, 2024, "rejected", ["social"],
     "Help for everyone in any situation. Write to us and we will find volunteers for you very fast."),
]

# org index -> coordinators (name, email, phone, position, owner)
COORDS = {
    1: [("Dana Serikbayeva", "org@demeu.kz", "+77015550101", "Programme director", 1),
        ("Arman Tulegenov", "arman@greensteppe.kz", "+77015550102", "Field coordinator", 0)],
    2: [("Malika Imekeshova", "malika@pawsalmaty.kz", "+77025550201", "Shelter manager", 1),
        ("Timur Akhmetov", "timur@pawsalmaty.kz", "+77025550202", "Volunteer coordinator", 0)],
    3: [("Gulnara Abenova", "gulnara@bilimbridge.kz", "+77055550301", "Founder", 1)],
    4: [("Elena Kim", "elena@qamqorlyq.kz", "+77075550401", "Director", 1),
        ("Saule Zhakupova", "saule@qamqorlyq.kz", "+77075550402", "Social worker", 0)],
    5: [("Damir Ten", "damir@jaiyqkeepers.kz", "+77085550501", "Initiative leader", 1)],
    6: [("Aigerim Bekova", "aigerim@steppe-uni.kz", "+77015550601", "Club president", 1),
        ("Nurlan Ospanov", "nurlan@steppe-uni.kz", "+77015550602", "Events lead", 0)],
    7: [("Olga Petrenko", "olga@kindhands.kz", "+77025550701", "Coordinator", 1)],
    8: [("Ruslan Ibraimov", "ruslan@almatyrun.kz", "+77055550801", "Race volunteer lead", 1)],
    9: [("Yerlan Mukhamedov", "yerlan@altairescue.kz", "+77075550901", "Team leader", 1)],
    10: [("Asel Nurgaliyeva", "neworg@demeu.kz", "+77085551001", "Founder", 1)],
    11: [("Bolat Sarsenov", "quickhelp@inbox.kz", "+77085551101", "Director", 1)],
}

FIRST = ["Aruzhan", "Alisher", "Dias", "Madina", "Nurbek", "Zarina", "Aidana", "Yerassyl", "Kamila", "Tanya",
         "Daniyar", "Aliya", "Sanzhar", "Aigerim", "Miras", "Dana", "Ilyas", "Saltanat", "Alua", "Emil", "Alan",
         "Assel", "Bekzat", "Diana", "Arsen", "Togzhan", "Maxim", "Inkar", "Nursultan", "Sofia", "Yerlan",
         "Akbota", "Ramazan", "Anel", "Timur", "Zhansaya", "Kirill", "Meruyert", "Adil", "Laura"]
LAST_M = ["Bekzhanov", "Seilbekov", "Omarov", "Kenzhebayev", "Abdrakhmanov", "Nurlanov", "Kassymov", "Tokayev",
          "Zhumabekov", "Ivanov", "Akhmetov", "Sultanov", "Mukanov", "Baimukhanov"]
LAST_F = ["Kassymova", "Ospanova", "Bekova", "Kosareva", "Nurlanova", "Abenova", "Sadykova", "Zhakupova",
          "Tulegenova", "Iskakova", "Kairatova", "Smagulova", "Yessenova", "Petrova"]
FEMALE = {"Aruzhan", "Madina", "Zarina", "Aidana", "Kamila", "Tanya", "Aliya", "Aigerim", "Dana", "Saltanat",
          "Alua", "Assel", "Diana", "Togzhan", "Inkar", "Sofia", "Akbota", "Anel", "Zhansaya", "Meruyert", "Laura"}
SKILLS = ["first aid certificate", "English (B2)", "driver's licence B", "photography", "SMM", "Kazakh sign language",
          "working with children", "basic carpentry", "Python and Excel", "event hosting", "cooking for groups",
          "psychology student", "veterinary student", "guitar", "Russian/Kazakh/English", "logistics"]
ABOUT = [
    "Student who likes to spend weekends outdoors and wants to make my city cleaner.",
    "I work in IT and volunteer on Saturdays. Happy to help with anything that needs a laptop or a strong back.",
    "Medical student. Interested in donation days and first-aid duty at public events.",
    "I have two dogs from a shelter, so animal welfare is personal for me.",
    "Retired teacher. I tutor children in maths and Kazakh and visit care homes.",
    "School student in grade 10, collecting volunteer hours for university applications.",
    "I love big events: marathons, festivals, concerts. Good at guiding crowds and staying calm.",
    "Photographer. I take photos at charity events for free so organisations can use them.",
]

# (direction, title, summary, description, requirements, provided, start hour, duration h, capacity, min_age, approval)
TEMPLATES = [
    ("ecology", "City Park Clean-up",
     "Collect litter and sort it for recycling in one of the central parks.",
     "We meet at the main entrance, split into teams of five and clean the park territory, lake shore and "
     "playgrounds. Plastic, glass and paper are sorted on the spot and taken by our recycling partner. "
     "A short safety briefing is given before the start.",
     "Comfortable closed shoes and clothes for the weather.", "Gloves, bags, tea and sandwiches.", 10, 3, 40, 14, 0),
    ("ecology", "Autumn Tree Planting",
     "Plant 300 young trees with the city greening department.",
     "Volunteers plant saplings of elm, birch and pine along the new park alley. Every team gets a mentor from "
     "the greening department who shows how to plant and water the tree correctly.",
     "Work clothes; ability to work with a shovel.", "Shovels, gloves, hot lunch.", 9, 5, 60, 16, 0),
    ("ecology", "Riverbank Restoration Day",
     "Clean the river coast and plant willows to stop erosion.",
     "Part of the team clears the shoreline from plastic and old tyres, the other part plants willow cuttings "
     "on the slope. We finish with a picnic for all participants.",
     "Rubber boots are recommended.", "Gloves, bags, water, picnic.", 10, 4, 35, 14, 1),
    ("ecology", "Eco-lesson for Schoolchildren",
     "Teach grade 5–7 pupils how to sort waste at home.",
     "Volunteers run a 45-minute interactive lesson in pairs using our ready presentation and game cards. "
     "Training for new volunteers takes 30 minutes before the lesson.",
     "Friendly attitude; basic presentation skills.", "Lesson materials and training.", 14, 2, 8, 18, 1),
    ("animals", "Weekend Dog Walking",
     "Walk and socialise shelter dogs that are waiting for a family.",
     "Each volunteer walks two or three dogs on the shelter territory and nearby field. Staff explain the "
     "character of every dog. Walking helps dogs stay calm and get adopted faster.",
     "Age 16+; not afraid of large dogs.", "Leads, treats, tea.", 11, 3, 15, 16, 1),
    ("animals", "Shelter Enclosure Repair",
     "Repair winter enclosures and insulate dog houses before the cold.",
     "We fix fences, replace boards and put straw insulation into dog houses. Tools are provided; experience "
     "with tools is welcome but not required.",
     "Work clothes and gloves.", "Tools, materials, hot lunch.", 10, 6, 12, 18, 1),
    ("animals", "Adoption Day at the Mall",
     "Help shelter cats and dogs meet future families.",
     "Volunteers talk to visitors, show animals and help fill adoption forms. Two shifts of three hours.",
     "Polite communication; Kazakh or Russian.", "Volunteer vest, lunch.", 12, 3, 10, 16, 1),
    ("children", "Mentoring Meeting with Orphanage Graduates",
     "Share your experience about studies and work with young people leaving care.",
     "A small-group meeting where mentors and graduates discuss choosing a profession, writing a CV and "
     "managing money. Each mentor is paired with one or two graduates.",
     "Age 21+; university degree or working experience.", "Coffee break; mentor guide.", 15, 3, 10, 21, 1),
    ("children", "Creative Workshop in a Children's Hospital",
     "Run crafts and drawing activities for children in long-term treatment.",
     "Volunteers bring a calm creative activity for children in the paediatric department. A medical check "
     "is required: a recent fluorography result.",
     "Fluorography not older than 1 year.", "Craft materials, masks.", 16, 2, 6, 18, 1),
    ("seniors", "Home Visits to Lonely Elderly",
     "Visit elderly people, talk, help with shopping and small home tasks.",
     "Volunteers go in pairs to the addresses given by the social worker. A visit lasts about two hours. "
     "Before the first visit you get a 30-minute briefing.",
     "Patience and kindness; age 18+.", "Briefing, transport compensation.", 11, 3, 12, 18, 1),
    ("seniors", "Concert in a Care Home",
     "Prepare and perform a small concert for residents of a care home.",
     "Singers, musicians and hosts are welcome. After the concert we have tea with residents and talk.",
     "Any performing skill, or help with hosting.", "Sound equipment, tea.", 15, 2, 15, 14, 1),
    ("education", "Free Maths & English Tutoring",
     "Tutor school pupils from low-income families in small groups.",
     "Every tutor works with a group of 3–4 pupils of grades 5–9 using the programme of the initiative.",
     "Good school-level maths or English (B1+).", "Workbooks, classroom.", 15, 2, 10, 17, 1),
    ("digital", "Digital Literacy for Seniors",
     "Teach older people to use eGov, banking apps and video calls safely.",
     "One volunteer works with one or two older people. We practise how to receive a digital document, "
     "pay utilities and recognise phone fraud.",
     "Confident smartphone user; patience.", "Training plan, tea.", 11, 3, 12, 16, 1),
    ("digital", "Kids Robotics Workshop",
     "Help children aged 8–13 build and program simple robots.",
     "Volunteers assist the main teacher: help teams assemble LEGO robots and debug simple programs.",
     "Interest in technology; no experience needed.", "Kits, snacks.", 14, 3, 8, 16, 1),
    ("social", "Food Parcel Packing",
     "Pack food parcels for 200 families registered with the social service.",
     "Volunteers work on a conveyor: weigh, pack and label parcels, then load them into the delivery van.",
     "Ability to stand and lift up to 10 kg.", "Lunch, gloves.", 10, 4, 25, 14, 0),
    ("social", "Warm Clothes Collection Point",
     "Receive, sort and pack donated winter clothes.",
     "We sort clothes by size and season, check their condition and pack them for delivery to families.",
     "None.", "Tea, packing materials.", 12, 4, 15, 14, 0),
    ("health", "Blood Donation Day",
     "Help donors register and support the medical team during the donation day.",
     "Volunteers meet donors, help them fill in the questionnaire, guide them through the stations and offer "
     "tea after donation. Volunteers 18+ may also donate if they wish.",
     "Polite communication.", "Volunteer badge, lunch.", 9, 5, 12, 16, 1),
    ("culture", "City Day Festival Volunteers",
     "Work at information points, children's zone and navigation during the festival.",
     "Volunteers are split into zones; each zone has a team leader. Shifts are 4 hours long.",
     "Age 16+; Kazakh or Russian; English is a plus.", "T-shirt, meal, certificate.", 12, 4, 80, 16, 1),
    ("culture", "Charity Book Fair",
     "Run the book stands and cashless donation point at the charity fair.",
     "Volunteers arrange books, consult visitors and help with the donation terminal. All money goes to the "
     "school library project.",
     "None.", "Snacks.", 11, 5, 20, 14, 0),
    ("sport", "Half-Marathon Water Station",
     "Hand out water and keep the station clean along the race course.",
     "Each water station has 10 volunteers and a captain. Arrive 1.5 hours before the start for the briefing.",
     "Age 16+; ready to stand for several hours.", "Event T-shirt, breakfast, lunch.", 7, 6, 60, 16, 0),
    ("sport", "Kids Football Tournament",
     "Help referees, keep score and look after teams at a children's tournament.",
     "A friendly tournament for 16 school teams. Volunteers work as field assistants and at the registration desk.",
     "None.", "Lunch, T-shirt.", 10, 6, 20, 14, 0),
    ("emergency", "Flood Preparedness: Sandbag Training",
     "Learn to fill and lay sandbags together with the emergency services.",
     "A practical training before the spring flood season. Instructors show safe lifting, filling and laying "
     "sandbag walls. Participants join the reserve list for real calls.",
     "Age 18+; good physical condition.", "Gloves, lunch, insurance for the day.", 10, 5, 30, 18, 1),
    ("emergency", "First Aid Course for Volunteers",
     "A free practical first-aid course with a certified instructor.",
     "Theory and practice: CPR, bleeding control, recovery position. A certificate is given after the exam.",
     "Age 16+.", "Training materials, certificate.", 10, 6, 20, 16, 1),
]

ORG_TEMPLATES = {1: ["City Park Clean-up", "Autumn Tree Planting", "Eco-lesson for Schoolchildren", "Riverbank Restoration Day"],
                 2: ["Weekend Dog Walking", "Shelter Enclosure Repair", "Adoption Day at the Mall"],
                 3: ["Free Maths & English Tutoring", "Digital Literacy for Seniors", "Kids Robotics Workshop"],
                 4: ["Home Visits to Lonely Elderly", "Concert in a Care Home", "Food Parcel Packing"],
                 5: ["Riverbank Restoration Day", "City Park Clean-up"],
                 6: ["Mentoring Meeting with Orphanage Graduates", "City Day Festival Volunteers", "Charity Book Fair",
                     "Kids Football Tournament", "Creative Workshop in a Children's Hospital"],
                 7: ["Food Parcel Packing", "Warm Clothes Collection Point", "Blood Donation Day"],
                 8: ["Half-Marathon Water Station", "City Day Festival Volunteers"],
                 9: ["Flood Preparedness: Sandbag Training", "First Aid Course for Volunteers", "Riverbank Restoration Day"]}
PLACES = {
    "Astana": ["Central Park, main entrance", "Presidential Park, south gate", "Botanical Garden", "Esil river embankment near Triumph bridge",
               "School No. 54, Kenesary St 40", "Steppe University campus, block C1"],
    "Almaty": ["Shelter territory, Talgar highway 7 km", "Mega Center Alma-Ata, ground floor", "Gorky Park, central alley",
               "Abay Ave and Dostyk Ave crossing, start area", "Republic Square"],
    "Shymkent": ["Youth Center, Tauke Khan Ave 30", "Central Library, Baitursynov St 2", "School No. 12"],
    "Karaganda": ["Care home No. 2, Mustafin St 7", "Social service office, Bukhar Zhyrau Ave 49", "Central Park Karaganda"],
    "Uralsk": ["Ural river coast near Kirov bridge", "Uralsk city beach", "Victory Park"],
    "Kostanay": ["Kind Hands warehouse, Al-Farabi Ave 115", "Regional Blood Centre, Tauelsizdik St 85", "Central Mall"],
    "Ust-Kamenogorsk": ["Emergency Department training ground", "Altai Rescue base, Kazakhstan St 64", "Irtysh embankment"],
}
FEEDBACK = [
    (5, "Very well organised: clear briefing, all tools ready, and the coordinator thanked everyone personally."),
    (5, "Great team and atmosphere. I came alone and left with new friends. Will join again!"),
    (4, "Good event, but the start was 20 minutes late. Otherwise everything was clear."),
    (5, "I liked that hours were confirmed the same evening and the certificate was available right away."),
    (4, "Useful work, we really saw the result. It would be nice to have more water on a hot day."),
    (5, "The coordinator explained everything patiently. Perfect for first-time volunteers."),
    (3, "The idea is good, but there were too many volunteers for the amount of work."),
    (5, "Meaningful and well planned. Thank you for the warm lunch!"),
    (5, "My first volunteering experience and definitely not the last. Everyone was friendly."),
    (4, "Good organisation. Please send the meeting point map a day earlier next time."),
    (5, "We finished everything planned and even more. Proud of our team!"),
    (4, "Nice event, a bit cold in the morning — bring warm clothes."),
    (5, "Clear tasks for every group, no one was standing without work."),
    (5, "Came with my sister, both of us enjoyed it. Thank you to the coordinators!"),
    (4, "Useful experience for my university portfolio, and the certificate came quickly."),
    (5, "Kind people and a real result you can see. Highly recommend."),
    (3, "Registration at the start took too long; maybe use a QR check-in."),
    (5, "Great safety briefing — even beginners felt confident."),
]


def dt(d):
    return d.strftime(FMT)


def main():
    if "--reset" in sys.argv and os.path.exists(DB):
        os.remove(DB)
    if os.path.exists(DB):
        print("Database already exists:", DB, "(use --reset to recreate)")
        return
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA, encoding="utf-8") as f:
        con.executescript(f.read())
    x = con.execute
    pw = generate_password_hash(PASSWORD)

    for c in CITIES:
        x("INSERT INTO cities (name_en,name_ru,name_kk,region_en,lat,lng) VALUES (?,?,?,?,?,?)", c)
    for d in DIRECTIONS:
        x("INSERT INTO directions (slug,name_en,name_ru,name_kk,icon,tone) VALUES (?,?,?,?,?,?)", d)

    admin_id = x("INSERT INTO users (email,password_hash,role,created_at) VALUES (?,?, 'admin', ?)",
                 ("admin@demeu.kz", pw, dt(NOW - timedelta(days=400)))).lastrowid

    # ---------------- organisations & coordinators
    coord_ids = {}
    for i, o in enumerate(ORGS, start=1):
        name, bin_, typ, city, addr, email, phone, site, founded, status, dirs, desc = o
        created = NOW - timedelta(days=380 - i * 8) if status == "verified" else NOW - timedelta(days=3 + i)
        x("""INSERT INTO organizations (org_id,name,bin,org_type,description,city_id,address,email,phone,website,
             founded_year,status,status_comment,verified_at,verified_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (i, name, bin_, typ, desc, C[city], addr, email, phone, site, founded, status,
           "BIN does not match the state register; please upload the registration certificate." if status == "rejected" else None,
           dt(created + timedelta(days=1)) if status == "verified" else None,
           admin_id if status == "verified" else None, dt(created)))
        for dslug in dirs:
            x("INSERT INTO organization_directions VALUES (?,?)", (i, D[dslug]))
        coord_ids[i] = []
        for cn, ce, cp, pos, owner in COORDS[i]:
            uid = x("INSERT INTO users (email,password_hash,role,created_at) VALUES (?,?, 'coordinator', ?)",
                    (ce, pw, dt(created))).lastrowid
            cid = x("INSERT INTO coordinators (user_id,org_id,full_name,phone,position,is_owner,created_at) VALUES (?,?,?,?,?,?,?)",
                    (uid, i, cn, cp, pos, owner, dt(created))).lastrowid
            coord_ids[i].append(cid)

    # ---------------- volunteers (ids 1001..), Aruzhan = 1024 to match the Task 9 example
    city_pool = ["Astana"] * 6 + ["Almaty"] * 5 + ["Shymkent"] * 3 + ["Karaganda"] * 2 + ["Uralsk", "Kostanay",
                 "Ust-Kamenogorsk", "Pavlodar", "Aktobe", "Atyrau", "Turkestan"]
    vols = []
    used_names = set()
    for n in range(70):
        vid = 1001 + n
        if vid == 1024:
            first, last, email, city, birth = "Aruzhan", "Kassymova", "volunteer@demeu.kz", "Astana", date(2004, 9, 20)
        elif vid == 1005:
            first, last, email, city, birth = "Nurbek", "Seilbekov", "minor@demeu.kz", "Astana", \
                date(NOW.year - 16, 2, 15)
        elif vid == 1012:
            first, last, email, city, birth = "Dana", "Iskakova", "dana.iskakova@mail.kz", "Almaty", \
                date(NOW.year - 17, 5, 3)
        else:
            while True:
                first = rnd.choice(FIRST)
                last = rnd.choice(LAST_F if first in FEMALE else LAST_M)
                if (first, last) not in used_names and first not in ("Aruzhan",):
                    break
            city = rnd.choice(city_pool)
            email = f"{first.lower()}.{last.lower()}@{rnd.choice(['gmail.com', 'mail.kz', 'student.kz', 'inbox.kz'])}"
            birth = date(rnd.randint(1972, 2007), rnd.randint(1, 12), rnd.randint(1, 28))
        used_names.add((first, last))
        created = NOW - timedelta(days=rnd.randint(330, 420)) if n < 62 else NOW - timedelta(days=rnd.randint(2, 25))
        uid = x("INSERT INTO users (email,password_hash,role,preferred_lang,created_at,last_login_at) VALUES (?,?, 'volunteer',?,?,?)",
                (email, pw, "en" if vid in (1005, 1024) else rnd.choice(["en", "ru", "kk"]), dt(created), dt(NOW - timedelta(days=rnd.randint(0, 20))))).lastrowid
        phone = "+770" + str(rnd.randint(10000000, 99999999))
        about = rnd.choice(ABOUT) if rnd.random() < 0.8 else None
        skills = ", ".join(rnd.sample(SKILLS, rnd.randint(1, 3))) if rnd.random() < 0.75 else None
        is_public = 0 if n in (7, 19, 33, 51) else 1
        show = 1 if rnd.random() < 0.3 else 0
        if vid == 1024:
            about = "Third-year ecology student at Steppe University. I organise clean-ups in my district and " \
                    "want every park in Astana to have recycling bins."
            skills, show = "first aid certificate, English (B2), photography", 1
        x("""INSERT INTO volunteers (volunteer_id,user_id,full_name,phone,birth_date,city_id,about,skills,is_public,
             show_contacts,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
          (vid, uid, f"{first} {last}", phone, birth.isoformat(), C[city], about, skills, is_public, show, dt(created)))
        my_dirs = rnd.sample(list(D.values()), rnd.randint(2, 4))
        if vid == 1024:
            my_dirs = [D["ecology"], D["animals"], D["education"]]
        for d in my_dirs:
            x("INSERT INTO volunteer_directions VALUES (?,?)", (vid, d))
        vols.append(dict(id=vid, uid=uid, city=city, birth=birth, dirs=set(my_dirs), name=f"{first} {last}", created=created))

    # consents: Dana approved, Nurbek pending
    x("""INSERT INTO consents (volunteer_id,parent_name,parent_phone,file_path,status,reviewed_by,reviewed_at,uploaded_at)
         VALUES (1012,'Marat Iskakov','+77017778899','consents/sample_consent.pdf','approved',?,?,?)""",
      (admin_id, dt(NOW - timedelta(days=40)), dt(NOW - timedelta(days=42))))
    x("""INSERT INTO consents (volunteer_id,parent_name,parent_phone,file_path,status,uploaded_at)
         VALUES (1005,'Gulmira Seilbekova','+77023334455','consents/sample_consent.pdf','pending',?)""",
      (dt(NOW - timedelta(hours=20)),))

    # ---------------- events
    tpl = {t[1]: t for t in TEMPLATES}
    events = []
    eid = 300

    def make_event(org, title, start, status="published", coord=None, approval=None, cap=None, city=None):
        nonlocal eid
        eid += 1
        t = tpl[title]
        dslug, _, summary, desc, req, prov, hour, dur, capacity, min_age, appr = t
        city = city or ORGS[org - 1][3]
        start = start.replace(hour=hour, minute=0)
        end = start + timedelta(hours=dur)
        deadline = (start - timedelta(days=1)).replace(hour=20, minute=0)
        place = rnd.choice(PLACES.get(city, [ORGS[org - 1][4]]))
        created = min(start - timedelta(days=rnd.randint(12, 25)), NOW - timedelta(days=1))
        x("""INSERT INTO events (event_id,org_id,coordinator_id,direction_id,city_id,title,summary,description,address,
             starts_at,ends_at,registration_deadline,max_volunteers,min_age,requires_approval,requirements,provided,
             status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (eid, org, coord or rnd.choice(coord_ids[org]), D[dslug], C[city], title, summary, desc,
           f"{city}, {place}", dt(start), dt(end), dt(deadline), cap or capacity, min_age,
           appr if approval is None else approval, req, prov, status, dt(created)))
        ev = dict(id=eid, org=org, start=start, end=end, deadline=deadline, cap=cap or capacity, dur=dur,
                  min_age=min_age, dir=D[dslug], city=city, status=status, approval=appr, title=title, created=created)
        events.append(ev)
        return ev

    # past events (last ~10 months), event 310 = City Park Clean-up in Astana
    past_specs = []
    for org, titles in ORG_TEMPLATES.items():
        for title in titles:
            for _k in range(rnd.randint(1, 2)):
                past_specs.append((org, title, NOW - timedelta(days=rnd.randint(14, 300))))
    rnd.shuffle(past_specs)
    past_specs.sort(key=lambda s: s[2])
    for i, (org, title, start) in enumerate(past_specs):
        if eid + 1 == 310:
            make_event(1, "City Park Clean-up", NOW - timedelta(days=45), status="completed", cap=40)
            continue
        make_event(org, title, start, status="completed")
    # finished recently, attendance not yet confirmed (for the coordinator demo)
    make_event(1, "Autumn Tree Planting", NOW - timedelta(days=2), status="published")
    make_event(2, "Weekend Dog Walking", NOW - timedelta(days=1), status="published")
    make_event(6, "Charity Book Fair", NOW - timedelta(days=3), status="published")
    # upcoming
    up = [(1, "City Park Clean-up", 3), (1, "Eco-lesson for Schoolchildren", 9), (1, "Riverbank Restoration Day", 16),
          (2, "Weekend Dog Walking", 4), (2, "Adoption Day at the Mall", 11), (2, "Shelter Enclosure Repair", 18),
          (3, "Digital Literacy for Seniors", 5), (3, "Kids Robotics Workshop", 12), (3, "Free Maths & English Tutoring", 6),
          (4, "Home Visits to Lonely Elderly", 7), (4, "Concert in a Care Home", 20), (5, "City Park Clean-up", 8),
          (6, "City Day Festival Volunteers", 14), (6, "Mentoring Meeting with Orphanage Graduates", 10),
          (6, "Kids Football Tournament", 24), (7, "Blood Donation Day", 9), (7, "Warm Clothes Collection Point", 5),
          (8, "Half-Marathon Water Station", 21), (9, "First Aid Course for Volunteers", 13),
          (9, "Flood Preparedness: Sandbag Training", 30)]
    for org, title, days in up:
        make_event(org, title, NOW + timedelta(days=days))
    make_event(1, "Autumn Tree Planting", NOW + timedelta(days=26), status="draft")
    cancelled = make_event(8, "Half-Marathon Water Station", NOW + timedelta(days=6), status="cancelled")
    x("UPDATE events SET cancel_reason=? WHERE event_id=?",
      ("The city postponed the race because of the weather forecast. New date will be announced.", cancelled["id"]))
    # a small event that is already full
    full_ev = make_event(2, "Adoption Day at the Mall", NOW + timedelta(days=2), cap=4, approval=0)

    # ---------------- registrations
    def age_at(v, d):
        b = v["birth"]
        return d.year - b.year - ((d.month, d.day) < (b.month, b.day))

    def can_join(v, ev):
        a = age_at(v, ev["start"].date())
        if a < ev["min_age"]:
            return False
        if a < 18 and v["id"] != 1012:  # only Dana has an approved consent
            return False
        return True

    # Task 9 example: registration 5501 = Aruzhan (1024) at event 310
    ev310 = next(e for e in events if e["id"] == 310)
    x("""INSERT INTO registrations (registration_id,volunteer_id,event_id,status,motivation,applied_at,decided_at,
         hours_confirmed,confirmed_by,confirmed_at) VALUES (5501,1024,310,'attended',?,?,?,?,?,?)""",
      ("I organise clean-ups in my district and want to help in the central park too.",
       dt(ev310["start"] - timedelta(days=6)), dt(ev310["start"] - timedelta(days=6)), 3.0,
       coord_ids[1][1], dt(ev310["end"] + timedelta(hours=3))))
    x("""INSERT INTO audit_log (user_id,action,entity,entity_id,old_value,new_value,created_at)
         VALUES ((SELECT user_id FROM coordinators WHERE coordinator_id=?),'hours_confirmed','registrations',5501,NULL,'3.0',?)""",
      (coord_ids[1][1], dt(ev310["end"] + timedelta(hours=3))))
    taken_slots = {1024: [(ev310["start"], ev310["end"])]}  # volunteer -> (start, end) of active registrations

    def overlaps(v, ev):
        return any(s < ev["end"] and e > ev["start"] for s, e in taken_slots.get(v["id"], []))

    for ev in events:
        if ev["status"] == "draft":
            continue
        is_past = ev["end"] < NOW
        candidates = [v for v in vols if can_join(v, ev)]
        rnd.shuffle(candidates)
        candidates.sort(key=lambda v: (ev["dir"] not in v["dirs"], v["city"] != ev["city"]))
        if ev is full_ev:
            n = 6
        elif is_past:
            n = min(len(candidates), max(3, int(ev["cap"] * rnd.uniform(0.35, 0.8))))
        else:
            n = min(len(candidates), int(ev["cap"] * rnd.uniform(0.15, 0.55)))
        n = min(n, 18)
        if ev["id"] == 310:
            n = 14
        approved_count = 0
        for v in candidates[:n]:
            if ev["id"] == 310 and v["id"] == 1024:
                continue
            if overlaps(v, ev):
                continue
            if is_past:
                applied = ev["deadline"] - timedelta(hours=rnd.randint(2, 200))
            else:  # upcoming: applications spread over the last two weeks
                applied = min(NOW - timedelta(hours=rnd.randint(2, 330)), ev["deadline"] - timedelta(hours=1))
                applied = max(applied, ev["created"] + timedelta(hours=1))
            if applied < v["created"]:  # account did not exist yet
                continue
            motivation = rnd.choice([None, None, "I have done similar work before and want to help.",
                                     "Looking for a meaningful weekend activity.", "Live nearby, can come early."])
            coord = rnd.choice(coord_ids[ev["org"]])
            if ev["status"] == "cancelled":
                status = rnd.choice(["approved", "pending"])
            elif is_past and ev["status"] == "completed":
                status = rnd.choices(["attended", "no_show", "cancelled", "rejected"], [78, 9, 8, 5])[0]
            elif is_past:  # finished, not marked yet
                status = rnd.choices(["approved", "cancelled"], [90, 10])[0]
            else:
                if ev is full_ev:
                    status = "approved" if approved_count < ev["cap"] else None
                    if status is None:
                        continue
                elif ev["approval"]:
                    status = rnd.choices(["pending", "approved", "rejected", "cancelled"], [45, 40, 5, 10])[0]
                else:
                    status = rnd.choices(["approved", "cancelled"], [92, 8])[0]
            if status in ("approved", "attended", "no_show"):
                if approved_count >= ev["cap"]:
                    continue
                approved_count += 1
            decided = None if status == "pending" else dt(applied + timedelta(hours=rnd.randint(1, 30)))
            hours = conf_by = conf_at = None
            if status == "attended":
                hours = float(ev["dur"]) if rnd.random() < 0.8 else float(max(1, ev["dur"] - rnd.choice([1, 2])))
                conf_by = coord
                conf_at = dt(ev["end"] + timedelta(hours=rnd.randint(2, 40)))
            note = "All places for this role are filled." if status == "rejected" else None
            rid = x("""INSERT INTO registrations (volunteer_id,event_id,status,motivation,applied_at,decided_at,decided_by,
                       decision_note,hours_confirmed,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (v["id"], ev["id"], status, motivation, dt(applied), decided,
                     coord if status in ("approved", "rejected", "attended", "no_show") and ev["approval"] else None,
                     note, hours, conf_by, conf_at)).lastrowid
            if status in ("pending", "approved", "attended"):
                taken_slots.setdefault(v["id"], []).append((ev["start"], ev["end"]))
            if status == "attended":
                x("""INSERT INTO audit_log (user_id,action,entity,entity_id,old_value,new_value,created_at)
                     VALUES ((SELECT user_id FROM coordinators WHERE coordinator_id=?),'hours_confirmed','registrations',?,NULL,?,?)""",
                  (conf_by, rid, str(hours), conf_at))
                if rnd.random() < 0.55:
                    r, c = rnd.choice(FEEDBACK)
                    x("INSERT INTO feedback (registration_id,rating,comment,created_at) VALUES (?,?,?,?)",
                      (rid, r, c if rnd.random() < 0.85 else None, dt(ev["end"] + timedelta(days=rnd.randint(1, 3)))))
                if rnd.random() < 0.3:
                    code = "".join(rnd.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
                    x("INSERT INTO certificates (registration_id,code,issued_at) VALUES (?,?,?)",
                      (rid, code, dt(ev["end"] + timedelta(days=rnd.randint(1, 10)))))
            if status == "no_show":
                x("""INSERT INTO audit_log (user_id,action,entity,entity_id,old_value,new_value,created_at)
                     VALUES ((SELECT user_id FROM coordinators WHERE coordinator_id=?),'marked_no_show','registrations',?,NULL,NULL,?)""",
                  (coord, rid, dt(ev["end"] + timedelta(hours=5))))

    # extra history for Aruzhan so her profile shows real activity
    aru = next(v for v in vols if v["id"] == 1024)
    for ev in events:
        if ev["status"] != "completed" or ev["id"] == 310 or ev["city"] != "Astana":
            continue
        if overlaps(aru, ev) or con.execute("SELECT 1 FROM registrations WHERE volunteer_id=1024 AND event_id=?",
                                            (ev["id"],)).fetchone():
            continue
        if ev["dir"] not in aru["dirs"] and rnd.random() < 0.6:
            continue
        rid = x("""INSERT INTO registrations (volunteer_id,event_id,status,applied_at,decided_at,hours_confirmed,
                   confirmed_by,confirmed_at) VALUES (1024,?,'attended',?,?,?,?,?)""",
                (ev["id"], dt(ev["start"] - timedelta(days=5)), dt(ev["start"] - timedelta(days=4)), float(ev["dur"]),
                 coord_ids[ev["org"]][0], dt(ev["end"] + timedelta(hours=6)))).lastrowid
        taken_slots.setdefault(1024, []).append((ev["start"], ev["end"]))
    x("INSERT INTO feedback (registration_id,rating,comment,created_at) VALUES (5501,5,?,?)",
      ("Our team collected 46 bags of litter, and half of it went to recycling. Well organised!",
       dt(ev310["end"] + timedelta(days=1))))
    x("INSERT INTO certificates (registration_id,code,issued_at) VALUES (5501,'DMU7K2Q9XA',?)",
      (dt(ev310["end"] + timedelta(days=2)),))
    # one upcoming approved + one pending for Aruzhan
    for ev in events:
        if ev["status"] == "published" and ev["start"] > NOW and ev["city"] == "Astana" and not overlaps(aru, ev):
            if con.execute("SELECT 1 FROM registrations WHERE volunteer_id=1024 AND event_id=?", (ev["id"],)).fetchone():
                continue
            st = "approved" if not con.execute("SELECT 1 FROM registrations WHERE volunteer_id=1024 AND status='approved'"
                                               " AND event_id IN (SELECT event_id FROM events WHERE starts_at > ?)",
                                               (dt(NOW),)).fetchone() else "pending"
            x("""INSERT INTO registrations (volunteer_id,event_id,status,applied_at,decided_at) VALUES (1024,?,?,?,?)""",
              (ev["id"], st, dt(NOW - timedelta(days=2)), dt(NOW - timedelta(days=1)) if st == "approved" else None))
            taken_slots.setdefault(1024, []).append((ev["start"], ev["end"]))
            if st == "pending":
                break

    # ---------------- notifications for demo accounts
    def note(email, kind, link, ago_h, read=0, **params):
        uid = con.execute("SELECT user_id FROM users WHERE email=?", (email,)).fetchone()[0]
        x("INSERT INTO notifications (user_id,kind,params,link,is_read,created_at) VALUES (?,?,?,?,?,?)",
          (uid, kind, json.dumps(params, ensure_ascii=False), link, read, dt(NOW - timedelta(hours=ago_h))))

    note("volunteer@demeu.kz", "n_hours_confirmed", "/me/", 24 * 44, 1, event="City Park Clean-up", hours="3")
    note("volunteer@demeu.kz", "n_approved", "/me/applications", 26, 0,
         event=con.execute("""SELECT e.title FROM registrations r JOIN events e USING (event_id)
                              WHERE r.volunteer_id=1024 AND r.status='approved' AND e.starts_at > ?""", (dt(NOW),)).fetchone()[0]
         if con.execute("SELECT 1 FROM registrations r JOIN events e USING (event_id) WHERE r.volunteer_id=1024 AND r.status='approved' AND e.starts_at > ?", (dt(NOW),)).fetchone() else "City Park Clean-up")
    note("minor@demeu.kz", "n_welcome_volunteer", "/me/profile", 30, 0)
    note("admin@demeu.kz", "n_admin_new_consent", "/admin/consents/queue", 20, 0, name="Nurbek Seilbekov")
    note("admin@demeu.kz", "n_admin_new_org", "/admin/organizations/10/review", 70, 0, org="Pavlodar Food Share")

    # ---------------- offices & contact messages
    offices = [
        ("Astana", 1, "Kabanbay Batyr Ave 11, office 301", "+77172000111", "astana@demeu.kz", "Mon–Fri 09:00–18:00", 51.1283, 71.4305),
        ("Almaty", 0, "Abay Ave 52, 3rd floor", "+77272000222", "almaty@demeu.kz", "Mon–Fri 09:00–18:00", 43.2405, 76.9172),
        ("Shymkent", 0, "Tauke Khan Ave 30, Youth Center", "+77252000333", "shymkent@demeu.kz", "Mon–Fri 10:00–18:00", 42.3155, 69.5869),
        ("Karaganda", 0, "Bukhar Zhyrau Ave 49, office 12", "+77212000444", "karaganda@demeu.kz", "Tue–Sat 10:00–17:00", 49.8019, 73.1021),
    ]
    for city, head, addr, phone, email, hours, lat, lng in offices:
        x("INSERT INTO offices (city_id,is_head,address,phone,email,hours,lat,lng) VALUES (?,?,?,?,?,?,?,?)",
          (C[city], head, addr, phone, email, hours, lat, lng))
    msgs = [("Aliya Nurlanova", "aliya.n@gmail.com", "organization",
             "We are a school parents' committee. Can we register as an organisation to recruit volunteers for school events?", 2),
            ("Maxim Ivanov", "maxim.ivanov@mail.kz", "technical",
             "I did not receive the confirmation for my hours after the tree planting. Could you check, please?", 6),
            ("Inkar Smagulova", "inkar@inbox.kz", "partnership",
             "Our coffee shop chain would like to give free drinks to volunteers with a DEMEU certificate.", 30)]
    for name, email, topic, text, ago in msgs:
        x("INSERT INTO contact_messages (name,email,topic,message,status,created_at) VALUES (?,?,?,?,?,?)",
          (name, email, topic, text, "new" if ago < 10 else "in_progress", dt(NOW - timedelta(hours=ago))))

    con.commit()
    # sample consent document so the admin can open it
    folder = os.path.join(BASE, "instance", "uploads", "consents")
    os.makedirs(folder, exist_ok=True)
    sample = os.path.join(BASE, "demeu", "static", "sample_consent.pdf")
    if os.path.exists(sample):
        with open(sample, "rb") as src, open(os.path.join(folder, "sample_consent.pdf"), "wb") as dst:
            dst.write(src.read())
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
              ("users", "volunteers", "organizations", "coordinators", "events", "registrations", "feedback",
               "certificates", "audit_log")}
    con.close()
    print("Database created:", DB)
    print(counts)
    print("Demo password for all accounts:", PASSWORD)


if __name__ == "__main__":
    main()
