import csv
import json
import logging
import os
import re
import requests
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv


logging.basicConfig(level=logging.DEBUG)
load_dotenv()

TOKEN = os.getenv("PYDIS-FORMS-TOKEN")

QUALIFIER_FORM_URL = "https://forms-api.pythondiscord.com/forms/cj10-2023-qualifier/responses"
CONFIRMATION_FORM_URL = "https://forms-api.pythondiscord.com/forms/cj10-2023-participation-confirmation/responses"

CSV_FOLDER = Path("csv")
QUALIFIED_CSV = CSV_FOLDER / "qualified.csv"
CONFIRMED_CSV = CSV_FOLDER / "confirmed.csv"
BLACKLIST_CSV = CSV_FOLDER / "blacklist.csv"
MANUAL_UPSERTIONS_CSV = CSV_FOLDER / "manual_upsertions.csv"
FINAL_PARTICIPANTS_CSV = CSV_FOLDER / "final_participants.csv"
FINAL_TEAMS_CSV = CSV_FOLDER / "final_teams.csv"

QUALIFIED_HEADERS = ["discord_id", "discord_username", "age", "timezone", "python_experience", "git_experience", "team_leader", "codejam_experience"]
CONFIRMED_HEADERS = ["discord_id", "github_username"]
BLACKLIST_HEADERS = ["discord_id", "discord_username", "github_username"]
FINAL_PARTICIPANTS_HEADERS = ["discord_id", "discord_username", "github_username", "timezone", "python_experience", "git_experience", "age", "codejam_experience", "team_leader", "lead_priority"]
# Manual upsertion headers should match final participants headers

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
    Record raw responses from qualifier form.
    Does not filter to only participants who have confirmed, and may include multiple records per person.
    """
    response = requests.get(QUALIFIER_FORM_URL, cookies={"token": TOKEN})
    response.raise_for_status()
    submissions = response.json()
    with open(QUALIFIED_CSV, "w", encoding="utf-8") as file:
        writer = csv.DictWriter(file, lineterminator="\n", fieldnames=QUALIFIED_HEADERS)
        writer.writeheader()
        for submission in submissions:
            try:
                person_info = {
                    "discord_id": submission["user"]["id"],
                    "discord_username": submission["user"]["username"],
                    "age": submission["response"]["age-range"],
                    "timezone": submission["response"]["timezone"],
                    "python_experience": submission["response"]["python-experience"],
                    "git_experience": submission["response"]["git-experience"],
                    "team_leader": submission["response"]["team-leader"],
                    "codejam_experience": submission["response"]["code-jam-experience"],
                }
                writer.writerow(person_info)
            except Exception as err:
                logging.exception(json.dumps(submission, indent=2))
                raise err
    logging.info(f"Retrieved {len(submissions)} qualifier responses")


def write_confirmed_csv():
    """
    Get responses from the confirmation form and write to CSV.
    """
    response = requests.get(CONFIRMATION_FORM_URL, cookies={"token": TOKEN})
    response.raise_for_status()
    submissions = response.json()
    participation_count = 0
    with open(CONFIRMED_CSV, "w") as file:
        writer = csv.DictWriter(file, lineterminator="\n", fieldnames=CONFIRMED_HEADERS)
        writer.writeheader()
        try:
            for submission in submissions:
                if submission["response"]["participation"] != "Yes":
                    continue
                participation_count += 1
                writer.writerow({
                    "discord_id": submission["user"]["id"],
                    "github_username": submission["response"]["github"],
                })
        except Exception as err:
            logging.exception(json.dumps(submission, indent=2))
            raise err
    logging.info(f"Retrieved {len(submissions)} confirmation responses, {participation_count} confirmed")


def write_final_participants_csv():
    """
    Cross reference qualified, confirmed, blacklisted, and upsertions to obtain the final list of pariticipants.
    Allows manual review and vetting for leaders before starting the team-forming.
    """
    with open(BLACKLIST_CSV, encoding="utf-8") as file:
        blacklist = {line["discord_id"] for line in csv.DictReader(file)}
    logging.info(f"Loaded {len(blacklist)} blacklisted people")
    
    with open(CONFIRMED_CSV, encoding="utf-8") as file:
        confirmed = {int(line["discord_id"]): line for line in csv.DictReader(file)}
    logging.info(f"Loaded {len(confirmed)} confirmed people")

    with open(QUALIFIED_CSV, encoding="utf-8") as file:
        qualified: dict[int, dict] = {}
        for person in csv.DictReader(file):
            d_id = int(person["discord_id"])
            if (d_id in blacklist) or (d_id not in confirmed):
                continue
            py_exp = person["python_experience"].replace("have possible worked", "have possibly worked") # Typo fix in 2023; if it is not 2023 you can delete this
            person["python_experience"] = PYTHON_EXPERIENCE.index(py_exp)
            person["git_experience"] = GIT_EXPERIENCE.index(person["git_experience"])
            qualified[d_id] = {**person, "github_username": confirmed[d_id]["github_username"]}
    logging.info(f"Loaded {len(qualified)} qualified people")

    try:
        with open(MANUAL_UPSERTIONS_CSV, encoding="utf-8") as file:
            upsertions = list(csv.DictReader(file))
        for upsertion in upsertions:
            d_id = int(upsertion["discord_id"])
            if d_id not in qualified:
                qualified[d_id] = {}
            upsertion = {key.strip(): val.strip() for key, val in upsertion.items()}
            upsertion = {key: val for key, val in upsertion.items() if val != ""}
            qualified[d_id].update(upsertion)
        logging.info(f"Loaded {len(upsertions)} upsertions")
    except FileNotFoundError:
        pass

    with open(FINAL_PARTICIPANTS_CSV, "w") as file:
        writer = csv.DictWriter(file, lineterminator="\n", fieldnames=FINAL_PARTICIPANTS_HEADERS)
        writer.writeheader()
        for d_id, person_info in qualified.items():
            person_info = {
                key: val
                for key,val in person_info.items()
                if key in FINAL_PARTICIPANTS_HEADERS
            }
            writer.writerow(person_info)
    

def load_final_participants() -> list[Person]:
    """
    Load the final participants to begin team-forming.
    The final participants CSV should already have been manually reviewed, leaders vetted, and lead_prority set.
    """
    with open(BLACKLIST_CSV, encoding="utf-8" ) as file:
        # These should already be filtered out, but this allows adding to the blacklist after manual vetting.
        blacklist = [int(line["discord_id"]) for line in csv.DictReader(file)]

    people: list[Person] = []
    with open(FINAL_PARTICIPANTS_CSV, encoding="utf-8") as file:
        for person_info in csv.DictReader(file):
            try:
                d_id = int(person_info["discord_id"])
                if d_id in blacklist:
                    continue
                name = person_info["discord_username"]
                gh_name = person_info["github_username"]
                tz = parse_tz(person_info["timezone"])
                exp = int(person_info["python_experience"]) + int(person_info["git_experience"])
                lead_priority = int(person_info["lead_priority"])
                people.append(Person(d_id, tz, exp, lead_priority, name=name, gh_name=gh_name))
            except Exception as err:
                logging.debug(json.dumps(person_info, indent=2))
                raise err

    # Sanity checks
    logging.info(f"Loaded info for {len(people)} participants")
    logging.info(f"Timezones: {sorted(Counter(p.tz for p in people).items())}")
    logging.info(f"Exp: {sorted(Counter(p.exp for p in people).items())}")
    logging.info(f"Leads: {sorted(Counter(p.lead_priority for p in people).items())}")
    return people

if __name__ == "__main__":
    write_qualified_csv()
    write_confirmed_csv()
    write_final_participants_csv()