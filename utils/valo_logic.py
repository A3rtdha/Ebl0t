import random
from .game_data import MAP_POOL, AGENT_POOL

def get_random_maps(count=3):
    return random.sample(MAP_POOL, count)

def split_teams(players):
    shuffled = players.copy()
    random.shuffle(shuffled)
    mid = len(shuffled) // 2
    # Распределяем остаток, если нечетное
    extra = 1 if len(shuffled) % 2 != 0 else 0
    team1 = shuffled[:mid + extra]
    team2 = shuffled[mid + extra:]
    return team1, team2

def assign_random_agents(players):
    assignments = {}
    for player in players:
        assignments[player] = random.choice(AGENT_POOL)
    return assignments

# --- НОВАЯ ФУНКЦИЯ ---
def get_random_agent():
    """Возвращает одного случайного агента"""
    return random.choice(AGENT_POOL)
