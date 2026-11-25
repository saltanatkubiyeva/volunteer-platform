import hashlib
import json
import os
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

from demeu.db import SKILLS as SKILL_TYPES

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DEMEU_DB") or os.path.join(BASE, "instance", "demeu.db")
SCHEMA = os.path.join(BASE, "demeu", "schema.sql")
PASSWORD = "Demeu2026!"
rnd = random.Random(2026)
NOW = datetime.now().replace(second=0, microsecond=0)
FMT = "%Y-%m-%d %H:%M"

CITIES = [
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

DIRECTIONS = [
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


def wipe_in_place(path):
    con = sqlite3.connect(path, timeout=10)
    con.execute("PRAGMA foreign_keys = OFF")
    names = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for name in names:
        con.execute(f'DROP TABLE IF EXISTS "{name}"')
    con.commit()
    con.close()


def main():
    wiped = False
    if "--reset" in sys.argv and os.path.exists(DB):
        try:
            os.remove(DB)
        except PermissionError:
            wipe_in_place(DB)
            wiped = True
    if os.path.exists(DB) and not wiped:
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

    x("""INSERT INTO consents (volunteer_id,parent_name,parent_phone,file_path,status,reviewed_by,reviewed_at,uploaded_at)
         VALUES (1012,'Marat Iskakov','+77017778899','consents/sample_consent.pdf','approved',?,?,?)""",
      (admin_id, dt(NOW - timedelta(days=40)), dt(NOW - timedelta(days=42))))
    x("""INSERT INTO consents (volunteer_id,parent_name,parent_phone,file_path,status,uploaded_at)
         VALUES (1005,'Gulmira Seilbekova','+77023334455','consents/sample_consent.pdf','pending',?)""",
      (dt(NOW - timedelta(hours=20)),))

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
    make_event(1, "Autumn Tree Planting", NOW - timedelta(days=2), status="published")
    make_event(2, "Weekend Dog Walking", NOW - timedelta(days=1), status="published")
    make_event(6, "Charity Book Fair", NOW - timedelta(days=3), status="published")
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
    full_ev = make_event(2, "Adoption Day at the Mall", NOW + timedelta(days=2), cap=4, approval=0)

    def age_at(v, d):
        b = v["birth"]
        return d.year - b.year - ((d.month, d.day) < (b.month, b.day))

    def can_join(v, ev):
        a = age_at(v, ev["start"].date())
        if a < ev["min_age"]:
            return False
        if a < 18 and v["id"] != 1012:
            return False
        return True

    ev310 = next(e for e in events if e["id"] == 310)
    x("""INSERT INTO registrations (registration_id,volunteer_id,event_id,status,motivation,applied_at,decided_at,
         hours_confirmed,confirmed_by,confirmed_at) VALUES (5501,1024,310,'attended',?,?,?,?,?,?)""",
      ("I organise clean-ups in my district and want to help in the central park too.",
       dt(ev310["start"] - timedelta(days=6)), dt(ev310["start"] - timedelta(days=6)), 3.0,
       coord_ids[1][1], dt(ev310["end"] + timedelta(hours=3))))
    x("""INSERT INTO audit_log (user_id,action,entity,entity_id,old_value,new_value,created_at)
         VALUES ((SELECT user_id FROM coordinators WHERE coordinator_id=?),'hours_confirmed','registrations',5501,NULL,'3.0',?)""",
      (coord_ids[1][1], dt(ev310["end"] + timedelta(hours=3))))
    taken_slots = {1024: [(ev310["start"], ev310["end"])]}

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
            else:
                applied = min(NOW - timedelta(hours=rnd.randint(2, 330)), ev["deadline"] - timedelta(hours=1))
                applied = max(applied, ev["created"] + timedelta(hours=1))
            if applied < v["created"]:
                continue
            motivation = rnd.choice([None, None, "I have done similar work before and want to help.",
                                     "Looking for a meaningful weekend activity.", "Live nearby, can come early."])
            coord = rnd.choice(coord_ids[ev["org"]])
            if ev["status"] == "cancelled":
                status = rnd.choice(["approved", "pending"])
            elif is_past and ev["status"] == "completed":
                status = rnd.choices(["attended", "no_show", "cancelled", "rejected"], [78, 9, 8, 5])[0]
            elif is_past:
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

    river = con.execute("""SELECT event_id FROM events WHERE title='Riverbank Restoration Day' AND status='published'
                           ORDER BY starts_at DESC LIMIT 1""").fetchone()
    if river:
        flaky = con.execute("""SELECT r.volunteer_id FROM registrations r
            WHERE r.event_id=? AND r.status='pending' AND r.volunteer_id NOT IN (1011, 1024)
            ORDER BY (SELECT COUNT(*) FROM registrations x WHERE x.volunteer_id=r.volunteer_id
                      AND x.status IN ('attended','no_show')) DESC LIMIT 1""", (river[0],)).fetchone()
        if flaky:
            last = [r[0] for r in con.execute("""SELECT r.registration_id FROM registrations r JOIN events e USING (event_id)
                WHERE r.volunteer_id=? AND r.status IN ('attended','no_show') ORDER BY e.starts_at DESC LIMIT 3""", (flaky[0],))]
            for rid in last:
                x("DELETE FROM feedback WHERE registration_id=?", (rid,))
                x("DELETE FROM certificates WHERE registration_id=?", (rid,))
                x("""UPDATE registrations SET status='no_show', hours_confirmed=NULL, confirmed_by=NULL, confirmed_at=NULL
                     WHERE registration_id=?""", (rid,))
                x("""UPDATE audit_log SET action='marked_no_show', new_value=NULL
                     WHERE entity='registrations' AND entity_id=? AND action='hours_confirmed'""", (rid,))

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

    astana = con.execute("SELECT city_id FROM cities WHERE name_en='Astana'").fetchone()[0]
    x("INSERT INTO subscriptions (volunteer_id, city_id) VALUES (1024, ?)", (astana,))
    for slug in ("ecology", "animals"):
        x("INSERT INTO subscriptions (volunteer_id, direction_id) SELECT 1024, direction_id FROM directions WHERE slug=?", (slug,))

    full = con.execute("""SELECT e.event_id, e.starts_at, e.ends_at, e.min_age FROM events e
        WHERE e.status='published' AND e.starts_at > ? AND e.max_volunteers <=
              (SELECT COUNT(*) FROM registrations r WHERE r.event_id=e.event_id AND r.status IN ('approved','attended'))
        ORDER BY e.starts_at LIMIT 1""", (dt(NOW),)).fetchone()
    if full:
        waiting = con.execute("""SELECT v.volunteer_id FROM volunteers v
            WHERE v.volunteer_id NOT IN (1005, 1011, 1024) AND v.birth_date <= date(?, '-' || ? || ' years')
            AND NOT EXISTS (SELECT 1 FROM registrations r WHERE r.volunteer_id=v.volunteer_id AND r.event_id=?)
            AND NOT EXISTS (SELECT 1 FROM registrations r JOIN events e USING (event_id) WHERE r.volunteer_id=v.volunteer_id
                            AND r.status IN ('pending','approved') AND e.starts_at < ? AND e.ends_at > ?)
            ORDER BY v.volunteer_id LIMIT 2""", (full[1][:10], max(full[3], 18), full[0], full[2], full[1])).fetchall()
        for i, (vid,) in enumerate(waiting):
            x("INSERT INTO waitlist (volunteer_id, event_id, joined_at) VALUES (?,?,?)",
              (vid, full[0], dt(NOW - timedelta(hours=30 - i * 5))))

    shift_plan = {
        "Riverbank Restoration Day": [("Clearing the riverbank", 0, 2, 20), ("Planting and waste sorting", 2, 4, 15)],
        "City Day Festival Volunteers": [("Info points and navigation", 0, 2, 40), ("Children's zone and clean-up", 2, 4, 40)],
    }
    for title, plan in shift_plan.items():
        row = con.execute("""SELECT event_id, starts_at FROM events WHERE title=? AND status='published' AND starts_at > ?
                             ORDER BY starts_at LIMIT 1""", (title, dt(NOW))).fetchone()
        if not row:
            continue
        start = datetime.strptime(row[1], "%Y-%m-%d %H:%M")
        ids = [x("""INSERT INTO event_shifts (event_id, title, starts_at, ends_at, max_volunteers, position)
                    VALUES (?,?,?,?,?,?)""", (row[0], name, dt(start + timedelta(hours=a)), dt(start + timedelta(hours=b)), need, pos)).lastrowid
               for pos, (name, a, b, need) in enumerate(plan)]
        for (rid,) in con.execute("SELECT registration_id FROM registrations WHERE event_id=? AND status IN ('pending','approved')",
                                  (row[0],)).fetchall():
            pick = rid % 4
            if pick < 2:
                x("UPDATE registrations SET preferred_shift_id=? WHERE registration_id=?", (ids[pick], rid))
            elif pick == 2:
                x("UPDATE registrations SET prefers_all_shifts=1 WHERE registration_id=?", (rid,))

    reporters = [r[0] for r in con.execute(
        "SELECT user_id FROM volunteers WHERE volunteer_id IN (1003, 1008, 1015, 1021) ORDER BY volunteer_id")]
    target_ev = con.execute("""SELECT event_id FROM events WHERE status='published' AND starts_at > ? AND org_id <> 1
                               AND event_id NOT IN (SELECT event_id FROM event_shifts)
                               AND event_id NOT IN (SELECT event_id FROM waitlist)
                               AND title NOT IN ('Concert in a Care Home', 'Weekend Dog Walking')
                               ORDER BY max_volunteers DESC, starts_at LIMIT 1""", (dt(NOW),)).fetchone()
    if target_ev and len(reporters) >= 4:
        x("""INSERT INTO complaints (reporter_id, event_id, reason, details, created_at) VALUES (?,?,?,?,?)""",
          (reporters[0], target_ev[0], "fraud", "The coordinator wrote in the group chat that every volunteer must pay 5,000 tenge for a T-shirt before the event.",
           dt(NOW - timedelta(hours=20))))
        x("""INSERT INTO complaints (reporter_id, event_id, reason, details, created_at) VALUES (?,?,?,?,?)""",
          (reporters[1], target_ev[0], "fraud", "Asked for a payment by Kaspi transfer to take part.", dt(NOW - timedelta(hours=6))))
        org2 = con.execute("SELECT org_id FROM organizations WHERE org_id <> 1 AND status='verified' ORDER BY org_id DESC LIMIT 1").fetchone()[0]
        x("""INSERT INTO complaints (reporter_id, org_id, reason, details, created_at) VALUES (?,?,?,?,?)""",
          (reporters[2], org2, "inappropriate", "The organization page has advertising of a private shop in the description.",
           dt(NOW - timedelta(days=3))))
        x("""INSERT INTO complaints (reporter_id, event_id, reason, details, status, action, admin_note, handled_by,
             created_at, handled_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
          (reporters[3], target_ev[0], "other", "The start time in the description differs from the time on the page.",
           "dismissed", "none", "Checked with the organizer: the time on the page is correct, the description was updated.",
           con.execute("SELECT user_id FROM users WHERE email='admin@demeu.kz'").fetchone()[0],
           dt(NOW - timedelta(days=9)), dt(NOW - timedelta(days=8))))

    lead = con.execute("""SELECT r.registration_id FROM registrations r JOIN events e USING (event_id)
        WHERE r.volunteer_id=1024 AND r.status='approved' AND e.starts_at > ? ORDER BY e.starts_at LIMIT 1""",
                       (dt(NOW),)).fetchone()
    if lead:
        x("UPDATE registrations SET is_team_lead=1 WHERE registration_id=?", lead)

    def note(email, kind, link, ago_h, read=0, **params):
        uid = con.execute("SELECT user_id FROM users WHERE email=?", (email,)).fetchone()[0]
        x("INSERT INTO notifications (user_id,kind,params,link,is_read,created_at) VALUES (?,?,?,?,?,?)",
          (uid, kind, json.dumps(params, ensure_ascii=False), link, read, dt(NOW - timedelta(hours=ago_h))))

    con.executemany("INSERT INTO skills (slug, name_en, name_ru, name_kk, icon, has_expiry) VALUES (?,?,?,?,?,?)", SKILL_TYPES)
    SK = {slug: sid for sid, slug in con.execute("SELECT skill_id, slug FROM skills")}
    admin_uid = con.execute("SELECT user_id FROM users WHERE email='admin@demeu.kz'").fetchone()[0]
    fstart = (NOW + timedelta(days=6)).replace(hour=10, minute=0, second=0, microsecond=0)
    food_id = x("""INSERT INTO events (org_id,coordinator_id,direction_id,city_id,title,summary,description,address,
         starts_at,ends_at,registration_deadline,max_volunteers,min_age,requires_approval,requirements,provided,
         status,created_at) VALUES (6,9,?,?,?,?,?,?,?,?,?,8,18,1,?,?,'published',?)""",
                (D["social"], C["Astana"], "Food Parcel Delivery to Families",
                 "Deliver food parcels by car to 40 families in the outskirts of Astana.",
                 "We load 40 food parcels at the warehouse at 10:00 and deliver them by your own car to families in Koktal and Industrialny districts. Each driver gets a route of 5 addresses and a partner who carries the boxes. Fuel is compensated.",
                 "Astana, Steppe University warehouse, Kabanbay Batyr 53", dt(fstart), dt(fstart + timedelta(hours=5)),
                 dt(fstart - timedelta(hours=24)), "Driver's licence and your own car", "Fuel compensation, lunch",
                 dt(NOW - timedelta(days=2)))).lastrowid
    for slug in ("driver_license", "own_car"):
        x("INSERT INTO event_requirements (event_id, skill_id) VALUES (?,?)", (food_id, SK[slug]))
    docs = [
        (1024, "driver_license", "2033-04-12", "pending", None, 5),
        (1024, "own_car", None, "pending", None, 5),
        (1011, "driver_license", "2031-09-01", "approved", None, 30),
        (1011, "own_car", None, "approved", None, 30),
        (1017, "driver_license", "2029-05-20", "approved", None, 20),
        (1017, "own_car", None, "approved", None, 20),
        (1009, "driver_license", "2030-01-15", "rejected", "The scan is blurred, the name is not readable. Please upload a clear photo.", 12),
        (1013, "driver_license", "2026-10-01", "approved", None, 200),
        (1021, "own_car", None, "pending", None, 26),
    ]
    for vid, slug, exp, st, comment, ago in docs:
        up = NOW - timedelta(hours=ago)
        x("""INSERT INTO volunteer_skills (volunteer_id, skill_id, file_path, expires_at, status, review_comment,
             reviewed_by, reviewed_at, uploaded_at) VALUES (?,?,?,?,?,?,?,?,?)""",
          (vid, SK[slug], "documents/sample_document.pdf", exp, st, comment,
           admin_uid if st != "pending" else None, dt(up + timedelta(hours=3)) if st != "pending" else None, dt(up)))
    kirill_free = not con.execute("""SELECT 1 FROM registrations r JOIN events e USING (event_id) WHERE r.volunteer_id=1011
        AND r.status IN ('pending','approved') AND e.starts_at < ? AND e.ends_at > ?""",
                                  (dt(fstart + timedelta(hours=5)), dt(fstart))).fetchone()
    if kirill_free:
        x("""INSERT INTO registrations (volunteer_id, event_id, status, motivation, applied_at)
             VALUES (1011, ?, 'pending', 'I have a minivan and can take more boxes than usual.', ?)""",
          (food_id, dt(NOW - timedelta(hours=20))))
    urgent = con.execute("SELECT event_id FROM events WHERE title='Warm Clothes Collection Point' AND starts_at > ?",
                         (dt(NOW),)).fetchone()
    if urgent:
        x("UPDATE events SET is_urgent=1, urgent_at=? WHERE event_id=?", (dt(NOW - timedelta(hours=3)), urgent[0]))

    fresh = [
        (1, 1, "ecology", "Tree Planting in the Botanical Garden",
         "Plant young birches and pines along the new alley of the Botanical Garden.",
         "We plant 300 seedlings along the new alley. Team leaders show how to plant, water and tie the young trees. Work in groups of five.",
         "Astana, Botanical Garden, south entrance", 9, 10, 3, 25, 14, 1, "Gloves and comfortable shoes", "Tools, water and tea", 30),
        (6, 9, "animals", "Insulating Dog Houses for Winter",
         "Help a city shelter prepare dog houses for the cold season.",
         "We line 20 dog houses with felt and straw and fix the roofs before the frost. No experience needed, the shelter staff explain everything on site.",
         "Astana, Happy Paws shelter, Koktal district", 12, 11, 4, 15, 16, 0, "Warm clothes you do not mind getting dirty", "Materials, gloves and hot lunch", 5),
    ]
    for org_id, coord_id, dslug, title, summary, desc, place, days, hour, dur, cap, age, appr, req, prov, ago in fresh:
        start = (NOW + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
        new_id = x("""INSERT INTO events (org_id,coordinator_id,direction_id,city_id,title,summary,description,address,
             starts_at,ends_at,registration_deadline,max_volunteers,min_age,requires_approval,requirements,provided,
             status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'published',?)""",
                   (org_id, coord_id, D[dslug], C["Astana"], title, summary, desc, place, dt(start),
                    dt(start + timedelta(hours=dur)), dt(start - timedelta(hours=24)), cap, age, appr, req, prov,
                    dt(NOW - timedelta(hours=ago)))).lastrowid
        note("volunteer@demeu.kz", "n_new_for_you", f"/events/{new_id}", ago, 0, event=title, date=dt(start)[:10])

    storm_start = (NOW + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    storm_id = x("""INSERT INTO events (org_id,coordinator_id,direction_id,city_id,title,summary,description,address,
         starts_at,ends_at,registration_deadline,max_volunteers,min_age,requires_approval,requirements,provided,
         status,is_urgent,urgent_at,created_at) VALUES (1,1,?,?,?,?,?,?,?,?,?,20,16,0,?,?,'published',1,?,?)""",
                 (D["ecology"], C["Astana"], "Storm Clean-up in Central Park",
                  "Clear broken branches and save young trees in Central Park after last night's storm.",
                  "Last night a strong wind broke dozens of trees in Central Park, and branches now block the paths and the playground. "
                  "City services are removing the fallen trunks, and we need volunteers to collect branches, rake the paths "
                  "and re-tie and support the young trees we planted in autumn before the frost. Team leaders show what to do on site.",
                  "Astana, Central Park, main entrance from Kenesary St", dt(storm_start), dt(storm_start + timedelta(hours=4)),
                  dt(storm_start - timedelta(hours=24)), "Warm clothes and boots",
                  "Work gloves, rakes, hot tea and lunch", dt(NOW - timedelta(hours=4)), dt(NOW - timedelta(hours=5)))).lastrowid
    storm_busy = """SELECT 1 FROM registrations r JOIN events e USING (event_id) WHERE r.volunteer_id=?
        AND r.status IN ('pending','approved') AND e.starts_at < ? AND e.ends_at > ?"""
    joined = 0
    for vid in (1011, 1017, 1003, 1007, 1015):
        if not con.execute(storm_busy, (vid, dt(storm_start + timedelta(hours=4)), dt(storm_start))).fetchone():
            x("""INSERT INTO registrations (volunteer_id, event_id, status, applied_at, decided_at)
                 VALUES (?, ?, 'approved', ?, ?)""", (vid, storm_id, dt(NOW - timedelta(hours=3)), dt(NOW - timedelta(hours=3))))
            joined += 1
    for (email,) in con.execute("""SELECT u.email FROM volunteers v JOIN users u USING (user_id) WHERE v.city_id=? AND u.is_active=1
            AND v.volunteer_id NOT IN (SELECT volunteer_id FROM registrations WHERE event_id=?)""", (C["Astana"], storm_id)).fetchall():
        note(email, "n_urgent_call", f"/events/{storm_id}", 4, 0, event="Storm Clean-up in Central Park", org="Green Steppe",
             date=dt(storm_start)[:10], time="10:00", n=20 - joined)

    note("admin@demeu.kz", "n_admin_new_document", "/admin/documents", 5, 0, name="Aruzhan Kassymova")
    note("volunteer@demeu.kz", "n_hours_confirmed", "/me/", 24 * 44, 1, event="City Park Clean-up", hours="3")
    note("volunteer@demeu.kz", "n_approved", "/me/applications", 26, 0,
         event=con.execute("""SELECT e.title FROM registrations r JOIN events e USING (event_id)
                              WHERE r.volunteer_id=1024 AND r.status='approved' AND e.starts_at > ?""", (dt(NOW),)).fetchone()[0]
         if con.execute("SELECT 1 FROM registrations r JOIN events e USING (event_id) WHERE r.volunteer_id=1024 AND r.status='approved' AND e.starts_at > ?", (dt(NOW),)).fetchone() else "City Park Clean-up")
    note("minor@demeu.kz", "n_welcome_volunteer", "/me/profile", 30, 0)
    note("admin@demeu.kz", "n_admin_new_consent", "/admin/consents/queue", 20, 0, name="Nurbek Seilbekov")
    note("admin@demeu.kz", "n_admin_new_org", "/admin/organizations/10/review", 70, 0, org="Pavlodar Food Share")

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

    photo_src = os.path.join(BASE, "demeu", "static", "img", "photos")
    photo_dst = os.path.join(BASE, "instance", "uploads", "photos")
    os.makedirs(photo_dst, exist_ok=True)

    def last_completed(title, org_id):
        return con.execute("""SELECT event_id, ends_at FROM events WHERE title=? AND org_id=? AND status='completed'
                              ORDER BY starts_at DESC LIMIT 1""", (title, org_id)).fetchone()

    def attended_users(event_id):
        return [r[0] for r in con.execute("""SELECT v.user_id FROM registrations r JOIN volunteers v USING (volunteer_id)
            WHERE r.event_id=? AND r.status='attended' ORDER BY v.volunteer_id=1024 DESC, r.registration_id""", (event_id,))]

    def coord_user(org_id):
        return con.execute("SELECT user_id FROM coordinators WHERE org_id=? ORDER BY is_owner DESC LIMIT 1", (org_id,)).fetchone()[0]

    def add_photo(event, photo_id, user_id, hours_after, reviewed=True, hidden=None):
        name = f"{photo_id}.jpg"
        src = os.path.join(photo_src, name)
        if os.path.exists(src):
            with open(src, "rb") as a, open(os.path.join(photo_dst, name), "wb") as b:
                b.write(a.read())
        created = datetime.strptime(event[1], "%Y-%m-%d %H:%M") + timedelta(hours=hours_after)
        checked = dt(created + timedelta(hours=5)) if reviewed or hidden else None
        return x("""INSERT INTO event_photos (event_id, user_id, file_path, status, hide_reason, reviewed_by, reviewed_at, created_at)
                    VALUES (?,?,?,?,?,?,?,?)""",
                 (event[0], user_id, f"photos/{name}", "hidden" if hidden else "visible", hidden,
                  admin_uid if checked else None, checked, dt(created))).lastrowid

    park = last_completed("City Park Clean-up", 1)
    if park:
        people = attended_users(park[0])
        dana = coord_user(1)
        add_photo(park, "1758599668429-121d54188b9c", dana, 3)
        add_photo(park, "1758599668186-c47df67d025d", dana, 3)
        add_photo(park, "1758599668508-d8ec9eca1be3", people[0], 6)
        add_photo(park, "1758599668426-1cf242bb7667", people[1] if len(people) > 1 else dana, 20, reviewed=False)
        add_photo(park, "1544928147-79a2dbc1f389", people[2] if len(people) > 2 else dana, 26, hidden="unrelated")
    planting = last_completed("Autumn Tree Planting", 1)
    if planting:
        add_photo(planting, "1710361006404-a13d01802ce9", (attended_users(planting[0]) or [coord_user(1)])[0], 5)
    marathon = last_completed("Half-Marathon Water Station", 8)
    if marathon:
        add_photo(marathon, "1613936360976-8f35cf0e5461", coord_user(8), 4)
    festival = last_completed("City Day Festival Volunteers", 6)
    if festival:
        people = attended_users(festival[0])
        pid = add_photo(festival, "1782567531523-0144dc7352fc", people[1] if len(people) > 1 else coord_user(6), 8,
                        reviewed=False)
        if len(people) > 2:
            x("INSERT INTO photo_reports (photo_id, reporter_id, reason, details, created_at) VALUES (?,?,?,?,?)",
              (pid, people[2], "unsafe", "There are many children in the front rows, I am not sure their parents agreed.",
               dt(NOW - timedelta(hours=6))))
            note("admin@demeu.kz", "n_admin_photo_report", "/admin/photos", 6, 0)

    sunday = (NOW + timedelta(days=(6 - NOW.weekday()) % 7 or 7)).replace(hour=0, minute=0, second=0, microsecond=0)
    anns = [
        ("DEMEU now works in Kostanay! Kind Hands Kostanay is the first verified organization.",
         "DEMEU теперь работает в Костанае! Kind Hands Kostanay — первая проверенная организация.",
         "DEMEU енді Қостанайда! Kind Hands Kostanay — алғашқы тексерілген ұйым.",
         "info", "all", None, None, NOW - timedelta(days=40), NOW - timedelta(days=26), 1),
    ]
    sunday_txt = {"en": f"Sunday, {sunday.day} {sunday.strftime('%B')}",
                  "ru": f"в воскресенье, {sunday.day} {['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'][sunday.month - 1]},",
                  "kk": f"{sunday.day}.{sunday.month:02d}, жексенбі,"}
    for en, ru, kk, tone, aud, city_id, link, start, end, notified in anns:
        en, ru, kk = en.format(d=sunday_txt["en"]), ru.format(d=sunday_txt["ru"]), kk.format(d=sunday_txt["kk"])
        x("""INSERT INTO announcements (text_en, text_ru, text_kk, tone, audience, city_id, link, starts_at, ends_at,
             notified, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
          (en, ru, kk, tone, aud, city_id, link, dt(start), dt(end), notified, admin_uid, dt(start)))
        if notified and end > NOW:
            for (uid,) in con.execute("""SELECT u.user_id FROM users u JOIN volunteers v USING (user_id) WHERE v.city_id=?
                    UNION SELECT u.user_id FROM users u JOIN coordinators c USING (user_id) JOIN organizations o USING (org_id)
                    WHERE o.city_id=?""", (city_id, city_id)).fetchall():
                x("""INSERT INTO notifications (user_id, kind, params, link, is_read, created_at) VALUES (?,?,?,?,0,?)""",
                  (uid, "n_announcement", json.dumps(dict(en=en, ru=ru, kk=kk), ensure_ascii=False), link, dt(start)))

    ev_cols = [r[1] for r in con.execute("PRAGMA table_info(events)")
               if r[1] not in ("event_id", "starts_at", "ends_at", "registration_deadline", "created_at", "series_id",
                               "is_urgent", "urgent_at", "updated_at", "cancel_reason")]

    def copy_week(src_id, weeks, series_id):
        row = dict(zip(ev_cols, con.execute(f"SELECT {', '.join(ev_cols)} FROM events WHERE event_id=?", (src_id,)).fetchone()))
        times = con.execute("SELECT starts_at, ends_at, registration_deadline FROM events WHERE event_id=?", (src_id,)).fetchone()
        shifted = [dt(datetime.strptime(t, "%Y-%m-%d %H:%M") + timedelta(weeks=weeks)) for t in times]
        row.update(status="published", starts_at=shifted[0], ends_at=shifted[1], registration_deadline=shifted[2],
                   series_id=series_id, created_at=dt(NOW - timedelta(days=3)))
        cols = list(row)
        return x(f"INSERT INTO events ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols]).lastrowid

    sat = (NOW + timedelta(days=(5 - NOW.weekday()) % 7 or 7)).replace(hour=15, minute=0, second=0, microsecond=0)
    esil = x("""INSERT INTO events (org_id,coordinator_id,direction_id,city_id,title,summary,description,address,
         starts_at,ends_at,registration_deadline,max_volunteers,min_age,requires_approval,requirements,provided,
         status,lat,lng,created_at) VALUES (1,1,?,?,?,?,?,?,?,?,?,15,14,0,?,?,'published',51.145410,71.421730,?)""",
             (D["ecology"], C["Astana"], "Saturday Clean-up at the Esil Embankment",
              "Every Saturday we keep the Esil embankment clean: litter, plastic and sorting for recycling.",
              "A short weekly clean-up of the embankment between the Atyrau and Arkhar bridges. We meet at the pedestrian bridge, "
              "split into pairs and walk our part of the embankment with bags and pickers. Plastic and glass go to our recycling partner.",
              "Astana, Esil embankment, near the Atyrau pedestrian bridge", dt(sat), dt(sat + timedelta(hours=2)),
              dt(sat - timedelta(hours=24)), "Warm clothes and gloves", "Bags, pickers and hot tea",
              dt(NOW - timedelta(days=3)))).lastrowid
    x("UPDATE events SET series_id=? WHERE event_id=?", (esil, esil))
    for k in (1, 2, 3):
        copy_week(esil, k, esil)
    for vid in (1011, 1017, 1003, 1022):
        if not con.execute("""SELECT 1 FROM registrations r JOIN events e USING (event_id) WHERE r.volunteer_id=?
                AND r.status IN ('pending','approved') AND e.starts_at < ? AND e.ends_at > ?""",
                           (vid, dt(sat + timedelta(hours=2)), dt(sat))).fetchone():
            x("""INSERT INTO registrations (volunteer_id, event_id, status, applied_at, decided_at) VALUES (?,?, 'approved', ?, ?)""",
              (vid, esil, dt(NOW - timedelta(days=2)), dt(NOW - timedelta(days=2))))
    dogs = [r[0] for r in con.execute("""SELECT event_id FROM events WHERE title='Weekend Dog Walking' AND org_id=2
                                         AND status='published' ORDER BY starts_at""")]
    if dogs:
        for d_id in dogs:
            x("UPDATE events SET series_id=? WHERE event_id=?", (dogs[0], d_id))
        last = dogs[-1]
        for k in (1, 2):
            copy_week(last, k, dogs[0])

    fb_comments = [
        ("Came early and helped us set everything up.", 0),
        ("Calm and careful, followed the safety briefing.", 0),
        ("Took care of the new volunteers in the group.", 0),
        ("Worked until the very end, thank you!", 0),
        ("Very polite with people and always smiling.", 0),
        ("The children loved the games, they did not want to let them go.", 1),
        ("Explained the tasks to the kids patiently and clearly.", 1),
    ]
    frnd = random.Random(77)
    attended = con.execute("""SELECT r.registration_id, r.volunteer_id, e.coordinator_id, e.ends_at, d.slug, e.title, e.org_id
        FROM registrations r JOIN events e USING (event_id) JOIN directions d USING (direction_id)
        WHERE r.status='attended' ORDER BY r.registration_id""").fetchall()
    special = {("City Park Clean-up", 1024): (1, 1, 0, "Aruzhan led a group of five and sorted all the recycling. Always on time."),
               ("Eco-lesson for Schoolchildren", 1024): (1, 0, 1, "Ran the quiz for the 3rd grade, the kids were happy."),
               ("City Day Festival Volunteers", 1024): (1, 0, 0, None)}
    used = set()
    for rid, vid, coord, ends, slug, title, org_id in attended:
        key = (title, vid)
        if key in special and key not in used:
            used.add(key)
            thanks, reliable, kids, text = special[key]
        elif frnd.random() < (0.55 if vid in (1022, 1011, 1017, 1067) else 0.25):
            kids_ok = slug in ("children", "education")
            text, needs_kids = frnd.choice([c for c in fb_comments if kids_ok or not c[1]])
            thanks, reliable, kids = 1, int(frnd.random() < 0.6), int(kids_ok and (needs_kids or frnd.random() < 0.5))
            text = text if frnd.random() < 0.75 else None
        else:
            continue
        x("""INSERT INTO volunteer_feedback (registration_id, coordinator_id, is_thanks, is_reliable, good_with_children,
             comment, created_at) VALUES (?,?,?,?,?,?,?)""",
          (rid, coord, thanks, reliable, kids, text, dt(datetime.strptime(ends, "%Y-%m-%d %H:%M") + timedelta(hours=20))))
    note("volunteer@demeu.kz", "n_feedback_thanks", "/volunteers/1024", 24 * 44 - 2, 1,
         org="Green Steppe", event="City Park Clean-up")

    tim_created = NOW - timedelta(days=200)
    tim_uid = x("""INSERT INTO users (email,password_hash,role,preferred_lang,created_at,last_login_at)
                   VALUES ('timur@demeu.kz',?, 'volunteer','en',?,?)""", (pw, dt(tim_created), dt(NOW - timedelta(days=2)))).lastrowid
    x("""INSERT INTO volunteers (volunteer_id,user_id,full_name,phone,birth_date,city_id,about,skills,is_public,show_contacts,created_at)
         VALUES (1100,?,'Timur Sadykov','+77015550011','2002-03-11',?,?,?,1,1,?)""",
      (tim_uid, C["Astana"], "Software engineering student. I like outdoor clean-ups and helping at food banks.",
       "driving licence, Python", dt(tim_created)))
    for slug in ("ecology", "social"):
        x("INSERT INTO volunteer_directions VALUES (1100, ?)", (D[slug],))
    x("INSERT INTO subscriptions (volunteer_id, city_id) VALUES (1100, ?)", (C["Astana"],))
    x("INSERT INTO subscriptions (volunteer_id, direction_id) VALUES (1100, ?)", (D["ecology"],))
    tim_done = []
    for title in ("City Park Clean-up", "Autumn Tree Planting"):
        ev = last_completed(title, 1)
        if ev:
            st = con.execute("SELECT starts_at, ends_at FROM events WHERE event_id=?", (ev[0],)).fetchone()
            hrs = (datetime.strptime(st[1], "%Y-%m-%d %H:%M") - datetime.strptime(st[0], "%Y-%m-%d %H:%M")).seconds / 3600
            rid = x("""INSERT INTO registrations (volunteer_id,event_id,status,motivation,applied_at,decided_at,decided_by,
                       hours_confirmed,confirmed_by,confirmed_at) VALUES (1100,?,'attended',?,?,?,1,?,1,?)""",
                    (ev[0], "I live nearby and want to help.", dt(datetime.strptime(st[0], "%Y-%m-%d %H:%M") - timedelta(days=5)),
                     dt(datetime.strptime(st[0], "%Y-%m-%d %H:%M") - timedelta(days=4)), hrs, st[1])).lastrowid
            tim_done.append((rid, st[1]))
    if tim_done:
        x("INSERT INTO certificates (registration_id,code,issued_at) VALUES (?,'TMR4DEL8XQ',?)",
          (tim_done[0][0], dt(datetime.strptime(tim_done[0][1], "%Y-%m-%d %H:%M") + timedelta(days=1))))
        x("INSERT INTO feedback (registration_id,rating,comment,created_at) VALUES (?,5,?,?)",
          (tim_done[0][0], "Well organised, I will come again.", tim_done[0][1]))
        x("""INSERT INTO volunteer_feedback (registration_id, coordinator_id, is_thanks, is_reliable, comment, created_at)
             VALUES (?,1,1,1,'Timur brought extra bags and helped to carry everything to the van.',?)""",
          (tim_done[0][0], tim_done[0][1]))
    x("""INSERT INTO registrations (volunteer_id,event_id,status,motivation,applied_at,decided_at,decided_by)
         VALUES (1100,?,'approved','Saturdays work for me.',?,?,1)""", (esil, dt(NOW - timedelta(days=1)), dt(NOW - timedelta(days=1))))
    note("timur@demeu.kz", "n_approved", f"/events/{esil}", 24, 0, event="Saturday Clean-up at the Esil Embankment")

    trash_cols = [r[1] for r in con.execute("PRAGMA table_info(events)")
                  if r[1] not in ("event_id", "title", "status", "starts_at", "ends_at", "registration_deadline", "created_at",
                                  "deleted_at", "deleted_by", "series_id", "cancel_reason", "is_urgent", "urgent_at", "updated_at")]

    def trashed_event(src_id, title, status, days_ahead, deleted_ago, by_email, reason=None):
        start = (NOW + timedelta(days=days_ahead)).replace(hour=11, minute=0, second=0, microsecond=0)
        by = con.execute("SELECT user_id FROM users WHERE email=?", (by_email,)).fetchone()[0]
        cols = ", ".join(trash_cols)
        return x(f"""INSERT INTO events ({cols}, title, status, cancel_reason, starts_at, ends_at, registration_deadline,
                     created_at, deleted_at, deleted_by)
                     SELECT {cols}, ?, ?, ?, ?, ?, ?, ?, ?, ? FROM events WHERE event_id=?""",
                 (title, status, reason, dt(start), dt(start + timedelta(hours=3)), dt(start - timedelta(days=1)),
                  dt(NOW - timedelta(days=deleted_ago + 4)), dt(NOW - timedelta(days=deleted_ago)), by, src_id)).lastrowid

    trashed_event(367, "Winter Clothes Sorting Day", "draft", 20, 2, "org@demeu.kz")
    run_src = con.execute("SELECT event_id FROM events WHERE org_id=8 ORDER BY event_id LIMIT 1").fetchone()[0]
    run_owner = con.execute("""SELECT u.email FROM coordinators c JOIN users u USING (user_id)
                               WHERE c.org_id=8 ORDER BY c.is_owner DESC LIMIT 1""").fetchone()[0]
    trashed_event(run_src, "Night Run Water Point", "cancelled", 6, 28, run_owner, "The city moved the night run to spring.")
    x("UPDATE organizations SET deleted_at=?, deleted_by=? WHERE name='Quick Help KZ'",
      (dt(NOW - timedelta(days=12)), admin_uid))

    hist_cols = [r[1] for r in con.execute("PRAGMA table_info(events)")
                 if r[1] not in ("event_id", "title", "summary", "status", "starts_at", "ends_at", "registration_deadline",
                                 "created_at", "deleted_at", "deleted_by", "series_id", "cancel_reason", "is_urgent",
                                 "urgent_at", "updated_at", "direction_id", "max_volunteers")]
    astana_vols = [r[0] for r in con.execute("""SELECT v.volunteer_id FROM volunteers v JOIN cities c USING (city_id)
        WHERE c.name_en='Astana' AND v.volunteer_id NOT IN (1024, 1100, 1037) ORDER BY v.volunteer_id""")]
    hrnd = random.Random(2025)
    gs_coord = con.execute("SELECT coordinator_id FROM coordinators WHERE org_id=1 ORDER BY is_owner DESC LIMIT 1").fetchone()[0]
    history = [
        ("2025-04-19", "Spring Clean-up at the Esil Embankment", "ecology", 3), ("2025-05-24", "Tree Planting in Zhetisu District", "ecology", 4),
        ("2025-06-14", "Eco-quiz for Summer Camp Kids", "education", 2), ("2025-07-12", "Plastic-free Picnic in Central Park", "ecology", 3),
        ("2025-08-23", "Watering Young Trees on Turan Avenue", "ecology", 2), ("2025-09-20", "World Cleanup Day in Astana", "ecology", 4),
        ("2025-10-11", "Autumn Leaves Collection", "ecology", 3), ("2025-11-15", "Battery Collection Point at the Mall", "ecology", 3),
        ("2026-01-24", "Bird Feeders for the Botanical Garden", "ecology", 2), ("2026-02-21", "Eco-lesson at School No. 54", "education", 2),
        ("2026-04-18", "Clean-up Saturday at Lake Maly Taldykol", "ecology", 3), ("2026-07-11", "Eco-quiz for Summer Camp Kids", "education", 2),
        ("2026-08-22", "Watering Young Trees on Turan Avenue", "ecology", 2),
    ]
    hcols = ", ".join(hist_cols)
    for day, title, slug, hours in history:
        start = datetime.strptime(day + " 10:00", "%Y-%m-%d %H:%M")
        if start >= NOW:
            continue
        size = hrnd.randint(7, 14)
        eid = x(f"""INSERT INTO events ({hcols}, title, summary, status, starts_at, ends_at, registration_deadline, created_at,
                    direction_id, max_volunteers)
                    SELECT {hcols}, ?, ?, 'completed', ?, ?, ?, ?, ?, ? FROM events WHERE event_id=310""",
                (title, "A Green Steppe event for volunteers in Astana.", dt(start), dt(start + timedelta(hours=hours)),
                 dt(start - timedelta(days=1)), dt(start - timedelta(days=14)), D[slug], size + 4)).lastrowid
        x("UPDATE events SET coordinator_id=? WHERE event_id=?", (gs_coord, eid))
        for i, vid in enumerate(hrnd.sample(astana_vols, min(size, len(astana_vols)))):
            came = hrnd.random() > 0.12
            rid = x("""INSERT INTO registrations (volunteer_id, event_id, status, applied_at, decided_at, decided_by,
                       hours_confirmed, confirmed_by, confirmed_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (vid, eid, "attended" if came else "no_show", dt(start - timedelta(days=6)), dt(start - timedelta(days=5)),
                     gs_coord, hours if came else None, gs_coord if came else None,
                     dt(start + timedelta(hours=hours + 2)))).lastrowid
            if came and hrnd.random() < 0.3:
                x("INSERT INTO feedback (registration_id, rating, comment, created_at) VALUES (?,?,?,?)",
                  (rid, hrnd.choice([4, 5, 5, 5, 4, 3]), None, dt(start + timedelta(days=1))))

    for word in ("scam", "stupid", "idiot", "урод", "ватсап", "телеграм"):
        x("INSERT INTO banned_words (word, created_by, created_at) VALUES (?,?,?)", (word, admin_uid, dt(NOW - timedelta(days=20))))
    aru_uid = con.execute("SELECT user_id FROM volunteers WHERE volunteer_id=1024").fetchone()[0]
    park_regs = con.execute("""SELECT r.registration_id FROM registrations r LEFT JOIN feedback f USING (registration_id)
        WHERE r.event_id=310 AND r.status='attended' AND f.feedback_id IS NULL AND r.volunteer_id<>1024
        ORDER BY r.registration_id""").fetchall()
    if len(park_regs) >= 2:
        x("""INSERT INTO feedback (registration_id, rating, comment, status, is_hidden, flagged_words, created_at)
             VALUES (?,2,?, 'pending', 1, 'idiot', ?)""",
          (park_regs[0][0], "The organisers were idiots, nobody knew where to meet and we waited for 40 minutes.",
           dt(NOW - timedelta(hours=7))))
        spam = x("""INSERT INTO feedback (registration_id, rating, comment, created_at) VALUES (?,5,?,?)""",
                 (park_regs[1][0], "Great day! By the way, I sell cheap concert tickets, call me +7 701 555 22 11.",
                  dt(NOW - timedelta(days=3)))).lastrowid
        x("""INSERT INTO review_reports (feedback_id, reporter_id, reason, details, created_at) VALUES (?,?,'spam',?,?)""",
          (spam, aru_uid, "This is an advert, not a review.", dt(NOW - timedelta(hours=20))))
        note("admin@demeu.kz", "n_admin_review_pending", "/admin/reviews", 7, 0)
        note("admin@demeu.kz", "n_admin_review_report", "/admin/reviews", 20, 0)

    def vol_user(vid):
        return con.execute("SELECT user_id FROM volunteers WHERE volunteer_id=?", (vid,)).fetchone()[0]

    x("""INSERT INTO blocks (user_id, reason, starts_at, ends_at, blocked_by) VALUES (?,?,?,?,?)""",
      (vol_user(1037), "Did not come to four events in a row without warning the organisers.",
       dt(NOW - timedelta(days=2)), dt(NOW + timedelta(days=5)), admin_uid))
    x("""INSERT INTO blocks (user_id, reason, starts_at, ends_at, blocked_by) VALUES (?,?,?,?,?)""",
      (vol_user(1031), "Rude messages to a coordinator after the application was declined.",
       dt(NOW - timedelta(days=45)), dt(NOW - timedelta(days=15)), admin_uid))
    lifted_vid = con.execute("""SELECT volunteer_id FROM volunteers WHERE volunteer_id NOT IN (1024,1017,1037,1031,1001,1003,1011,1022,1100)
                                ORDER BY volunteer_id DESC LIMIT 1""").fetchone()[0]
    x("""INSERT INTO blocks (user_id, reason, starts_at, ends_at, blocked_by, lifted_at, lifted_by) VALUES (?,?,?,NULL,?,?,?)""",
      (vol_user(lifted_vid), "Uploaded someone else's driving licence as their own document.",
       dt(NOW - timedelta(days=50)), admin_uid, dt(NOW - timedelta(days=47)), admin_uid))
    x("""INSERT INTO blocks (org_id, reason, starts_at, blocked_by, lifted_at, lifted_by) VALUES (5,?,?,?,?,?)""",
      ("Two complaints about events with no coordinator on site. Restored after a call with the owner.",
       dt(NOW - timedelta(days=70)), admin_uid, dt(NOW - timedelta(days=66)), admin_uid))

    def deed(title, desc, slug, city, area, kind, days, people, name, email, phone, status, ago_days, **extra):
        when = (NOW + timedelta(days=days)).strftime("%Y-%m-%d") if kind != "any" else None
        created = NOW - timedelta(days=ago_days)
        tok = hashlib.sha256(f"seed-deed-{title}".encode()).hexdigest()
        cols = dict(title=title, description=desc, direction_id=D[slug], city_id=C[city], area=area, when_kind=kind,
                    when_date=when, people_needed=people, contact_name=name, contact_email=email, contact_phone=phone,
                    token_hash=tok, status=status, created_at=dt(created), confirmed_at=dt(created + timedelta(minutes=20)))
        if status not in ("pending", "unconfirmed"):
            cols.update(reviewed_by=admin_uid, reviewed_at=dt(created + timedelta(hours=5)))
        cols.update(extra)
        keys = list(cols)
        return x(f"INSERT INTO deed_requests ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
                 [cols[k] for k in keys]).lastrowid

    deed("New Year party for kids at the children's oncology ward",
         "The ward has 14 children who will spend the New Year holidays in hospital. Parents and nurses want a small party: "
         "Father Frost and Snow Maiden, games, crafts and gifts. We need volunteers to run games and help with decorations. "
         "The doctors allow visits in masks, no more than 10 people at a time.",
         "children", "Astana", "Astana, Regional Children's Hospital, Kerey and Zhanibek Khans St 3", "on", 33, 8,
         "Gulnara Sadykova", "gulnara.sadykova@gmail.com", "+77015552318", "open", 2)
    deed("Clear snow for an elderly neighbour",
         "My neighbour Raisa Ivanovna is 82 and lives alone in a private house. After every snowfall she cannot get out "
         "of the yard. Two or three people with shovels for an hour would help her a lot. Tea is on her!",
         "seniors", "Astana", "Astana, Saryarka district, Zhenis microdistrict", "any", 0, 3,
         "Daulet Abenov", "daulet.abenov@mail.kz", None, "open", 1)
    deed("Warm clothes for a family after a house fire",
         "A family with three children (4, 9 and 13 years old) lost their house in a fire last week. They need winter clothes "
         "and shoes. We would like volunteers to set up a collection point at school No. 72, sort the clothes by size and deliver them.",
         "social", "Astana", "Astana, school No. 72, Zhubanov St 5", "by", 12, 5,
         "Aigerim Tulegenova", "a.tulegenova@school72.kz", "+77473330912", "open", 3)
    deed("Paint the fence at the dog shelter",
         "The shelter fence is old and rusty; the paint is already bought. We need 6–8 people for one Saturday. "
         "Some of the dogs are nervous with strangers, so the shelter staff will show where it is safe to work.",
         "animals", "Almaty", "Almaty, Turksib district, shelter on Kazybayev St", "by", 20, 7,
         "Marat Ospanov", "marat.ospanov@gmail.com", None, "open", 4)
    deed("Reading club for kids at the city library",
         "The children's library wants to start a Saturday reading club for kids 7–10 years old. "
         "We are looking for volunteers who can read aloud in Kazakh or Russian and play simple word games.",
         "education", "Astana", "Astana, Children's Library named after Altynsarin", "on", 18, 4,
         "Saule Bekova", "saule.bekova@gmail.com", "+77012228844", "pending", 0)
    deed("Help us collect money for a new playground",
         "Please send any amount to the card number below, we need 2 million tenge for a playground in our yard.",
         "social", "Astana", "Astana, Almaty district", "any", 0, None,
         "Erlan K.", "erlan.k.2026@mail.ru", None, "rejected", 6,
         reject_reason="DEMEU does not collect money. You can suggest a clean-up or a building day instead.",
         closed_at=dt(NOW - timedelta(days=5)))
    gs_dana = con.execute("SELECT user_id FROM users WHERE email='org@demeu.kz'").fetchone()[0]
    gs_dana_coord = con.execute("SELECT coordinator_id FROM coordinators WHERE user_id=?", (gs_dana,)).fetchone()[0]
    yard_start = (NOW + timedelta(days=16)).replace(hour=11, minute=0, second=0, microsecond=0)
    yard_desc = ("The benches in our courtyard are broken and the flower beds are empty. Residents bought paint, boards and "
                 "200 tulip bulbs. We need people who can work with a screwdriver and a few who can plant bulbs.")
    yard_event = x("""INSERT INTO events (org_id, coordinator_id, direction_id, city_id, title, summary, description, address,
        starts_at, ends_at, registration_deadline, max_volunteers, min_age, requires_approval, status, created_at)
        VALUES (1,?,?,?,?,?,?,?,?,?,?,6,14,1,'draft',?)""",
                   (gs_dana_coord, D["ecology"], C["Astana"], "Repair benches and plant tulips in our courtyard",
                    yard_desc[:150].rsplit(" ", 1)[0] + "…", yard_desc, "Astana, Kenesary St 40, courtyard",
                    dt(yard_start), dt(yard_start + timedelta(hours=3)), dt(yard_start - timedelta(days=1)),
                    dt(NOW - timedelta(days=1)))).lastrowid
    deed("Repair benches and plant tulips in our courtyard", yard_desc, "ecology", "Astana",
         "Astana, Kenesary St 40, courtyard", "on", 16, 6, "Nurlan Akhmetov", "nurlan.akhmetov@inbox.kz", "+77019874411",
         "taken", 5, taken_org_id=1, taken_by=gs_dana, taken_at=dt(NOW - timedelta(days=1)), event_id=yard_event)
    deed("Weekly clean-up on the Esil embankment",
         "I run along the embankment every morning and there is more and more plastic near the Atyrau bridge. "
         "Could volunteers clean it regularly, maybe every Saturday?",
         "ecology", "Astana", "Astana, Esil embankment near the Atyrau bridge", "any", 0, 10,
         "Timur Aliyev", "timur.aliyev.run@gmail.com", None, "done", 12, taken_org_id=1, taken_by=gs_dana,
         taken_at=dt(NOW - timedelta(days=10)), event_id=esil, closed_at=dt(NOW - timedelta(days=4)))
    note("org@demeu.kz", "n_deed_new", "/org/requests", 26, 0, title="New Year party for kids at the children's oncology ward")
    note("admin@demeu.kz", "n_admin_deed", "/admin/good-deeds", 3, 0)

    for other, days in ((1011, 60), (1022, 45), (1023, 30), (1057, 20), (1019, 12)):
        x("""INSERT INTO friendships (requester_id, addressee_id, status, created_at, accepted_at)
             VALUES (?, 1024, 'accepted', ?, ?)""", (other, dt(NOW - timedelta(days=days)), dt(NOW - timedelta(days=days - 1))))
    x("INSERT INTO friendships (requester_id, addressee_id, created_at) VALUES (1046, 1024, ?)", (dt(NOW - timedelta(hours=3)),))
    x("INSERT INTO friendships (requester_id, addressee_id, created_at) VALUES (1024, 1047, ?)", (dt(NOW - timedelta(days=1)),))
    x("INSERT INTO kudos (from_id, to_id, milestone, created_at) VALUES (1011, 1024, 20, ?)", (dt(NOW - timedelta(days=50)),))
    note("volunteer@demeu.kz", "n_kudos", "/volunteers/1011", 24 * 50, 1, name="Kirill", n=20)
    note("volunteer@demeu.kz", "n_friend_milestone", "/me/friends", 26, 0, name="Ramazan", n=50, vid=1022)
    note("volunteer@demeu.kz", "n_friend_going", f"/events/{esil}", 5, 0, name="Kirill",
         event="Saturday Clean-up at the Esil Embankment")
    note("volunteer@demeu.kz", "n_friend_request", "/me/friends?tab=requests", 3, 0, name="Yerlan Ivanov")

    known_points = {
        "Storm Clean-up in Central Park": (51.152770, 71.436240),
        "Tree Planting in the Botanical Garden": (51.108560, 71.416340),
        "Food Parcel Delivery to Families": (51.090590, 71.418020),
        "Insulating Dog Houses for Winter": (51.177450, 71.540210),
    }
    for eid, title, lat, lng in con.execute("""SELECT e.event_id, e.title, c.lat, c.lng FROM events e
            JOIN cities c USING (city_id) WHERE e.lat IS NULL""").fetchall():
        if title in known_points:
            plat, plng = known_points[title]
        else:
            prnd = random.Random(eid * 7919)
            plat, plng = lat + prnd.uniform(-0.035, 0.035), lng + prnd.uniform(-0.055, 0.055)
        x("UPDATE events SET lat=?, lng=? WHERE event_id=?", (round(plat, 6), round(plng, 6), eid))

    con.commit()
    docs_dir = os.path.join(BASE, "instance", "uploads", "documents")
    os.makedirs(docs_dir, exist_ok=True)
    sample_doc = os.path.join(BASE, "demeu", "static", "sample_document.pdf")
    if os.path.exists(sample_doc):
        with open(sample_doc, "rb") as src, open(os.path.join(docs_dir, "sample_document.pdf"), "wb") as dst:
            dst.write(src.read())
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
