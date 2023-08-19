from load_data import load_final_participants, Person, write_confirmed_csv, write_qualified_csv


# Teams will end up this size or 1 larger.
TARGET_TEAM_SIZE = 5


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


def form_teams(people: list[Person]):
    """
    Pick leaders and form teams around them.
    Leaders are chosen to cover timezones while favoring lead_priority, with experience as a tie-breaker.
    Teams are chosen to keep each team's timezone span within reason and to equalize avg experience.
    """
    # Pick leaders
    potential_leaders = {person for person in people if person.lead_priority>0}
    if (len(potential_leaders)+1) * TARGET_TEAM_SIZE <= len(people):
        raise Exception("Not enough leaders for the target team size.")
    leaders: set[Person] = set()
    # Order by TZ, starting in the middle of the Pacific as a de facto start/end point,
    # then use every [TEAM_SIZE]th person's TZ as representative.
    # Easy way to get a leader distribution that roughly matches the overall distribution
    # while being resilient to arbitrary TZ boundaries.
    people = sorted(people, key=lambda p: (p.tz-12)%24)
    for person in people[TARGET_TEAM_SIZE//2::TARGET_TEAM_SIZE]:
        target_tz = person.tz
        best_match = max(
            potential_leaders,
            key=lambda pl: (
                # treat adjacent timezones the same as distance 0
                # we don't want to compromise on having good leaders unless it really stretches the timezone range
                -max(1.5, tz_dist(pl.tz, target_tz)),
                pl.lead_priority,
                pl.exp,
            )
        )
        leaders.add(best_match)
        potential_leaders.remove(best_match)

    # Form a team around each leader
    teams = [[leader] for leader in leaders]
    nonleaders = sorted((p for p in people if p not in leaders), key=lambda p: p.exp)
    global_exp_avg = sum(p.exp for p in people) / len(people)
    ends = (0, -1)
    for idx in range(len(nonleaders)):
        # Alternate between most/least experienced
        person = nonleaders.pop(ends[idx%2])
        team_options = [team for team in teams if 4 > tz_span(*[p.tz for p in team], person.tz)]
        if team_options:
            # Put on team that complements their exp level the best.
            best_team_match = max(team_options, key=lambda team: exp_improvement(person, team, global_exp_avg))
        else:
            # Put on team with closest TZ.
            best_team_match = min(teams, key=lambda team: tz_span(*[p.tz for p in team], person.tz))
        best_team_match.append(person)

    # Find easy changes
    for team in teams:
        # leader is the first in the list
        # replace a leader with a better one if they're already on the same team (should be rare)
        team[:] = sorted(team, key=lambda p: (p.lead_priority, p.exp), reverse=True)

    return teams


def write_teams_csv(teams: list[list[Person]]):
    ...

if __name__ == "__main__":
    # GET and write CSV
    # write_qualified_csv()

    # GET and write CSV
    # Possibly will be manual if we go with a bot button for confirmation.
    # write_confirmed_csv()

    # Cross reference qualified, confirmed, and blacklisted, then do manual upsertions
    people = load_final_participants()

    # Run algo
    teams = form_teams(people)
    
    # write_teams_csv(teams)

