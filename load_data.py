import csv
import json
import re
import requests
from collections import Counter
from pathlib import Path


TOKEN = ""

QUALIFIER_FORM_URL = "https://forms-api.pythondiscord.com/forms/cj10-2023-qualifier/responses"
CONFIRMATION_FORM_URL = ""

CSV_FOLDER = Path("csv")
QUALIFIED_CSV = CSV_FOLDER / "qualified.csv"
CONFIRMED_CSV = CSV_FOLDER / "confirmed.csv"
BLACKLIST_CSV = CSV_FOLDER / "blacklist.csv"
MANUAL_UPSERTIONS_CSV = CSV_FOLDER / "manual_upsertions.csv"
FINAL_TEAMS_CSV = CSV_FOLDER / "final_teams.csv"

# These are the literal form values. If the answers on the form are changed, these also need to be changed.
# The order of these matters.
PYTHON_EXPERIENCE = (
    "I'm a complete beginner, or I learned some of the basics of the language from courses or tutorials",
    "I'm OK, I've done a few projects in Python that are not related to courses or tutorials",
    "I have some experience with Python, and considerable experience in other languages",
    "I have considerable experience with the language, and have possibly worked with it professionally for several years",
)
GIT_EXPERIENCE = (
    "What is Git?",
    "I can commit, pull, push, etc., but I don't have much experience with it",
    "I'm pretty familiar with Git and use it regularly",
    "I can cherry-pick a remote branch using the disturbance ripples of butterflies",
)
LEADER = (
    "No",
    "I'm OK either way",
    "Yes",
)


class Person:
    def __init__(self, id: int, tz: float, exp: int, lead_priority: int, *, name: str = "", gh_name: str = ""):
        self.id = id
        self.tz = tz % 24
        self.exp = exp
        self.lead_priority = lead_priority
        self.name = name
        self.gh_name = gh_name

    def __eq__(self, other: "Person"):
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return f"Person({self.id}, TZ={self.tz}, EXP={self.exp}, LEAD={self.lead_priority})"


TZ_PATTERN = re.compile(r"([+-]?)(\d{1,2})(?::(\d{2}))?$")
def parse_tz(raw_string: str) -> float:
    """
    Input: timezone string e.g. "-12:30"
    Output: timezone float normalized to 0-24 e.g. 11.5
    """
    m = re.match(TZ_PATTERN, raw_string.strip())
    if m is None:
        raise Exception(f"Could not parse {raw_string} as a timezone")
    mult = 1 if m.group(1) in ("", "+") else -1
    hr = int(m.group(2))
    if m.group(3):
        hr += int(m.group(3))/60
    return (hr * mult) % 24


def write_qualified_csv():
    """
    Get responses from the qualifier form and write to CSV.
    """
    response = requests.get(QUALIFIER_FORM_URL, cookies={"token": TOKEN})
    response.raise_for_status()
    submissions = response.json()
    with open(QUALIFIED_CSV, "w") as file:
        writer = csv.writer(file)
        writer.writerow(["discord_username", "discord_id", "age", "timezone", "python_experience", "git_experience", "team_leader", "lead_priority", "code_jam_experience", "solution"])
        for submission in submissions:
            username = submission["user"]["username"]
            id = submission["user"]["id"]
            age = submission["response"]["age-range"]
            tz = submission["response"]["timezone"]
            py_exp = PYTHON_EXPERIENCE.index(submission["response"]["python-experience"])
            git_exp = GIT_EXPERIENCE.index(submission["response"]["git-experience"])
            team_leader = submission["response"]["team-leader"]
            cj_exp = submission["response"]["code-jam-experience"]
            solution = submission["response"]["solution"]
            writer.writerow([username, id, age, tz, py_exp, git_exp, team_leader, "", cj_exp, solution])


def load_final_participants() -> list[Person]:
    """
    Read the 4 CSVs and cross-reference to get final participants.
    """
    with open(BLACKLIST_CSV, encoding="utf-8") as file:
        blacklist = {line["discord_id"] for line in csv.DictReader(file)}
    
    with open(CONFIRMED_CSV, encoding="utf-8") as file:
        confirmed = {int(line["discord_id"]): line for line in csv.DictReader(file)}

    with open(QUALIFIED_CSV, encoding="utf-8") as file:
        qualified: dict[int, dict] = {}
        for line in csv.DictReader(file):
            d_id = int(line["discord_id"])
            if (d_id in blacklist) or (d_id not in confirmed):
                continue
            qualified[d_id] = {**line, "github_username": confirmed[d_id]["github_username"]}

    with open(MANUAL_UPSERTIONS_CSV, encoding="utf-8") as file:
        upsertions = {int(line["discord_id"]): line for line in csv.DictReader(file)}
    
    for d_id, upsertion in upsertions.items():
        if d_id not in qualified:
            qualified[d_id] = {}
        # Check validity/completeness of info?
        qualified[d_id].update(upsertion)

    people: list[Person] = []
    for d_id, person_info in qualified.items():
        try:
            person_info = {
                key.strip(): val.strip()
                for key,val in person_info.items()
                if key not in ("age", "solution", "code_jam_experience")
            }

            name = person_info["discord_username"]
            gh_name = person_info["github_username"]

            tz = parse_tz(person_info["timezone"])

            exp = int(person_info["python_experience"]) + int(person_info["git_experience"])

            if "lead_priority" in person_info:
                lead_priority = int(person_info["lead_priority"])
            else:
                lead_priority = LEADER.index(person_info["team_leader"])

            people.append(Person(d_id, tz, exp, lead_priority, name=name, gh_name=gh_name))

        except Exception as err:
            print(json.dumps(person_info, indent=2))
            raise err

    # Sanity checks
    print(f"Loaded info for {len(people)} participants")
    print(f"Timezones: {Counter(p.tz for p in people)}")
    print(f"Exp: {Counter(p.exp for p in people)}")
    print(f"Leads: {Counter(p.lead_priority for p in people)}")
    return people


#############


def write_confirmed_csv():
    """
    Get responses from the confirmation form and write to CSV.
    """
    response = requests.get(CONFIRMATION_FORM_URL, cookies={"token": TOKEN})
    response.raise_for_status()
    submissions = response.json()
    


