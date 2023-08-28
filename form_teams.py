import csv
import logging
from collections import Counter
from statistics import mean

from load_data import load_final_participants, Person


logging.basicConfig(level=logging.DEBUG)

# Teams will end up this size or 1 larger.
TARGET_TEAM_SIZE = 5
# Will try to keep teams within this span when forming teams.
TARGET_TZ_SPAN = 3
# Will attempt to fix teams with spans larger than this in a secondary phase.
MAX_TZ_SPAN = 4
# Will attempt to keep avg team exp levels within +/- from the global avg exp level.
# This is relative to the magnitude of the exp levels, so if the formula for that changes, this may need to be tweaked.
TARGET_EXP_RADIUS = 0.5
# In phase 3, the algo tries to fix problems by finding a person that fits on a team,
# and a person to replace them on the team they came from, etc.
# The time complexity is roughly O(n^depth), so be careful.
SWAP_CHAIN_SEARCH_DEPTH = 3


# Global state
PEOPLE: list[Person]
UNASSIGNED: set[Person]
TEAMS: list[list[Person]]
EXP_AVG: float


def tz_span(*tzs: tuple[float]) -> float:
    """
    Size of minimum window in which all the timezones fit.
    """
    tzs = sorted(tz%24 for tz in tzs)
    gaps = [b-a for a,b in zip(tzs, tzs[1:])]
    gaps.append(tzs[0] - tzs[-1] + 24)
    return 24 - max(gaps)


def tz_dist(x: float, y: float) -> float:
    """
    Distance between two timezones.
    Special case of tz_span implemented to be faster.
    """
    return min(abs(x-y), 24-abs(x-y))


def exp_improvement(candidate: Person, team: list[Person], global_avg: float) -> float:
    """
    Measure how much adding a person to a team would take its avg experience level closer to the global avg.
    """
    team_exp = sum(p.exp for p in team)
    before = team_exp/len(team) - global_avg
    after = (team_exp+candidate.exp)/(len(team)+1) - global_avg
    return before**2 - after**2


def form_teams():
    """
    Pick leaders and form teams around them.
    Leaders are chosen to cover timezones while favoring lead_priority, with experience as a tie-breaker.
    Teams are chosen to keep each team's timezone span within reason and to equalize avg experience.
    """
    logging.info(f"Forming teams with {len(PEOPLE)} people")
    logging.info(f"{TARGET_TEAM_SIZE=} {TARGET_TZ_SPAN=} {MAX_TZ_SPAN=} {TARGET_EXP_RADIUS=} {SWAP_CHAIN_SEARCH_DEPTH=}")
    logging.info(f"Average participant experience level: {EXP_AVG}")

    # Pick leaders
    logging.info("Picking team leaders to cover timezones")
    potential_leaders = {person for person in PEOPLE if person.lead_priority>0}
    if (len(potential_leaders)+1) * TARGET_TEAM_SIZE <= len(PEOPLE):
        raise Exception("Not enough leaders for the target team size.")
    leaders: set[Person] = set()
    # Order by TZ, starting in the middle of the Pacific as a de facto start/end point,
    # then use every [TEAM_SIZE]th person's TZ as representative.
    # Easy way to get a leader distribution that roughly matches the overall distribution
    # while being resilient to arbitrary TZ boundaries.
    PEOPLE.sort(key=lambda p: (p.tz-12)%24)
    for person in PEOPLE[TARGET_TEAM_SIZE//2::TARGET_TEAM_SIZE]:
        target_tz = person.tz
        best_leader_match = max(
            potential_leaders,
            key=lambda pl: (
                # treat adjacent timezones the same as distance 0
                # we don't want to compromise on having good leaders unless it really stretches the timezone range
                -max(TARGET_TZ_SPAN/2, tz_dist(pl.tz, target_tz)),
                pl.lead_priority,
                pl.exp,
            )
        )
        leaders.add(best_leader_match)
        potential_leaders.remove(best_leader_match)

    # Form a team around each leader
    global TEAMS, UNASSIGNED
    TEAMS = [[leader] for leader in leaders]
    UNASSIGNED = {p for p in PEOPLE if p not in leaders}

    logging.info(f"Initialized {len(TEAMS)} teams")
    logging.info(f"{len(UNASSIGNED)} people yet to be assigned")

    # Rotate through teams and have them draft people
    logging.info("Phase 1: teams draft good fits")
    for first_team in TEAMS*(TARGET_TEAM_SIZE-1):
        nearby_unassigned = [p for p in UNASSIGNED if MAX_TZ_SPAN >= tz_span(*[p.tz for p in first_team], p.tz)]
        if nearby_unassigned:
            # Else the team will be short and there will be an extra leftover to be resolved with swaps.
            best_match = max(
                nearby_unassigned,
                key=lambda person: (
                    # Treat timezone spans within the target span the same
                    # to allow the experience to matter as long as they're within a reasonable timezone window.
                    -max(TARGET_TZ_SPAN, tz_span(*[p.tz for p in first_team], person.tz)),
                    exp_improvement(person, first_team, EXP_AVG),
                )
            )
            first_team.append(best_match)
            UNASSIGNED.remove(best_match)
    
    logging.info(f"{sum(len(team) for team in TEAMS)} people assigned to teams")
    logging.info(f"{len(UNASSIGNED)} people yet to be assigned")

    # Assign leftovers to form teams of [TARGET_TEAM_SIZE]+1
    logging.info(f"Phase 2: assigning leftovers")
    for person in UNASSIGNED.copy():
        available_teams = [
            team for team in TEAMS
            if len(team) <= TARGET_TEAM_SIZE
            and tz_span(*[p.tz for p in team], person.tz) <= MAX_TZ_SPAN
        ]
        if available_teams:
            best_team_match = max(
                available_teams,
                key=lambda team: (
                    -max(TARGET_TZ_SPAN, tz_span(*[p.tz for p in team], person.tz)),
                    exp_improvement(person, team, EXP_AVG),
                ),
            )
            best_team_match.append(person)
            UNASSIGNED.remove(person)
    
    logging.info(f"{sum(len(team) for team in TEAMS)} people assigned to teams")
    logging.info(f"{len(UNASSIGNED)} people yet to be assigned")

    # Finding beneficial swaps for too-small teams
    logging.info("Phase 3: finding swaps")
    for team_id, team in enumerate(TEAMS):
        # For each person the team is short, search for a suitable match among teams.
        for _ in range(TARGET_TEAM_SIZE - len(team)):
            swap_chain = find_swap(
                team,
                {team_id},
                search_depth=3,
                skip_unassigned=True,
            )
            if swap_chain is None:
                break
            swap_chain_string = "\n\t".join(str(person) for person in swap_chain)
            logging.debug(f"Executing swap chain:\n\t{swap_chain_string}")
            target_team = team
            for person, from_team_id in swap_chain:
                target_team.append(person)
                if from_team_id is None:
                    # If it is None, the person was unassigned and they should be the last one in the chain
                    UNASSIGNED.remove(person)
                    target_team = None  # Break things if something weird happens
                else:
                    TEAMS[from_team_id].remove(person)
                    target_team = TEAMS[from_team_id]

    # Replace leader if there is a strictly better one on the same team (should be rare)
    for team in TEAMS:
        new_order = sorted(team, key=lambda p: (p.lead_priority, p.exp), reverse=True)
        if new_order[0] != team[0]:
            logging.debug(f"Replacing {team[0]} as leader with {new_order[0]}")
            team[:] = new_order

    logging.info(f"{sum(len(team) for team in TEAMS)} people assigned to teams")
    logging.info(f"{len(UNASSIGNED)} people yet to be assigned")


def find_swap(
    target_team: list[Person],
    involved_teams: set[int],
    search_depth: int = 1,
    skip_unassigned: bool = False,
) -> tuple[tuple[Person, int], ...]:
    """
    Find a person that would fit on target_team.
    If needed, recurse to find a replacement for the team they came from.
    Returns a chain of people to get reassigned.
    """
    # First check if any unassigned people fit on the target team.
    if not skip_unassigned:
        for person in UNASSIGNED:
            target_team_tz_span = tz_span(*[p.tz for p in target_team], person.tz)
            target_team_exp_avg = mean([p.exp for p in target_team] + [person.exp])
            if target_team_tz_span <= MAX_TZ_SPAN and abs(EXP_AVG - target_team_exp_avg) <= TARGET_EXP_RADIUS:
                return ((person, None),)

    # Then check for people from other teams that are large enough not to require replacement.
    for from_team_id, from_team in enumerate(TEAMS):
        if from_team_id in involved_teams or len(from_team) < TARGET_TEAM_SIZE + 1:
            continue
        # Don't want to swap leaders, so skip them.
        for person in from_team[1:]:
            target_team_tz_span = tz_span(*[p.tz for p in target_team], person.tz)
            from_team_tz_span = tz_span(*[p.tz for p in from_team if p != person])
            target_team_exp_avg = mean([p.exp for p in target_team] + [person.exp])
            from_team_exp_avg = mean([p.exp for p in from_team if p != person])
            if all((
                target_team_tz_span <= MAX_TZ_SPAN,
                from_team_tz_span <= MAX_TZ_SPAN,
                abs(EXP_AVG - target_team_exp_avg) <= TARGET_EXP_RADIUS,
                abs(EXP_AVG - from_team_exp_avg) <= TARGET_EXP_RADIUS,
            )):
                return ((person, from_team_id),)

    if search_depth <= 1:
        return None
    
    # Finally check for swaps that require a replacement.
    for from_team_id, from_team in enumerate(TEAMS):
        if from_team_id in involved_teams or len(from_team) < TARGET_TEAM_SIZE:
            continue
        for person in from_team[1:]:
            target_team_tz_span = tz_span(*[p.tz for p in target_team], person.tz)
            target_team_exp_avg = mean([p.exp for p in target_team] + [person.exp])
            if target_team_tz_span <= MAX_TZ_SPAN and abs(EXP_AVG - target_team_exp_avg) <= TARGET_EXP_RADIUS:
                # This would be a good swap for target_team, but first need to find a replacement for from_team
                # logging.debug(f"Looking for a replacement for {person.id}  (depth={search_depth})")
                swap = find_swap(
                    [p for p in from_team if p!=person],
                    {*involved_teams, from_team_id},
                    search_depth - 1,
                )
                if swap is not None:
                    return ((person, from_team_id), *swap)


def write_teams_csv():
    with open("csv/final_teams.csv", "w") as file:
        writer = csv.DictWriter(file, lineterminator="\n", fieldnames=("discord_id", "timezone", "exp", "lead_priority"))
        writer.writeheader()
        for team in TEAMS:
            for person in team:
                writer.writerow({
                    "discord_id": person.id,
                    "timezone": person.tz,
                    "exp": person.exp,
                    "lead_priority": person.lead_priority,
                })
            writer.writerow({})
        writer.writerow({})
        for person in UNASSIGNED:
            writer.writerow({
                "discord_id": person.id,
                "timezone": person.tz,
                "exp": person.exp,
                "lead_priority": person.lead_priority,
            })


def generate_teams_report():
    """
    Check how well the team-forming algo did.
    """
    teams = []
    with open("csv/final_teams.csv", encoding="utf-8") as file:
        team = []
        for person in csv.DictReader(file):
            if person["discord_id"]:
                person["timezone"] = float(person["timezone"])
                person["exp"] = int(person["exp"])
                person["lead_priority"] = int(person["lead_priority"])
                team.append(person)
            else:
                teams.append(team)
                team = []
    
    teams = [team for team in teams if team]
    sizes = sorted(Counter(len(team) for team in teams).items())
    time_spans = sorted(Counter(tz_span(*[p["timezone"] for p in team]) for team in teams).items())
    avg_exp = sorted(f"{mean(p['exp'] for p in team):.1f}" for team in teams)

    print("Team Sizes", sizes, sep="\n")
    print("Team Timezone Spans", time_spans, sep="\n")
    print("Team Avg Experience", avg_exp, sep="\n")


if __name__ == "__main__":
    PEOPLE = load_final_participants()
    assert len(PEOPLE) == len(set(PEOPLE))
    EXP_AVG = mean(p.exp for p in PEOPLE)

    form_teams()
    write_teams_csv()

    assert sum(len(team) for team in TEAMS) + len(UNASSIGNED) == len(PEOPLE)
    for team in TEAMS:
        assert len(set(team) & UNASSIGNED) == 0
        for second_team in TEAMS:
            if team != second_team:
                assert len(set(team) & set(second_team)) == 0
    assert all(any(p in team for team in TEAMS) or p in UNASSIGNED for p in PEOPLE)

    assert all(team[0].lead_priority > 0 for team in TEAMS)
    assert all(tz_span(*[p.tz for p in team]) <= MAX_TZ_SPAN for team in TEAMS)

    if UNASSIGNED:
        logging.warning("SOME PEOPLE ARE STILL UNASSIGNED")
    if not all(TARGET_TEAM_SIZE <= len(team) <= TARGET_TEAM_SIZE+1 for team in TEAMS):
        logging.warning("SOME TEAMS ARE AN INVALID SIZE")

    # Run analysis on generated teams
    generate_teams_report()