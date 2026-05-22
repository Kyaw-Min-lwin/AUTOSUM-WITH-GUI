import math
import heapq

class AStarPathfinder:

    def __init__(self, cell_size=0.1, obstacle_padding=0.04, max_iterations=5000):
        # cell_size: The size of each grid square in meters
        # obstacle_padding: How wide to treat walls (Wall width + Robot radius)
        self.cell_size = cell_size
        self.padding = obstacle_padding
        self.max_iterations = max_iterations

    def to_grid(self, pos):
        """Converts continuous world coordinates to discrete grid integers."""
        return (int(round(pos[0] / self.cell_size)), int(round(pos[1] / self.cell_size)))

    def to_world(self, grid_pos):
        """Converts grid integers back to continuous world coordinates."""
        return (grid_pos[0] * self.cell_size, grid_pos[1] * self.cell_size)

    def heuristic(self, a, b):
        """Standard Euclidean distance heuristic."""
        return math.sqrt((a[0] - b[0])**2 + (a[1] - b[1])**2)

    def find_path(self, start_pos, target_pos, obstacle_positions):
        start_node = self.to_grid(start_pos)
        target_node = self.to_grid(target_pos)

        # Convert continuous obstacle positions into a set of grid coordinates
        # We also add padding around them so the robot doesn't clip corners!
        blocked_nodes = set()
        pad_cells = int(round(self.padding / self.cell_size))

        for obs in obstacle_positions:
            obs_grid = self.to_grid(obs)
            for dx in range(-pad_cells, pad_cells + 1):
                for dy in range(-pad_cells, pad_cells + 1):
                    blocked_nodes.add((obs_grid[0] + dx, obs_grid[1] + dy))

        # Standard A* Setup
        open_set = []
        heapq.heappush(open_set, (0, start_node))
        came_from = {}
        
        g_score = {start_node: 0}
        f_score = {start_node: self.heuristic(start_node, target_node)}

        iterations = 0

        while open_set:
            iterations += 1
            if iterations > self.max_iterations:
                print("[Pathfinder] Timed out! Target might be unreachable.")
                return [] # Fail gracefully

            current = heapq.heappop(open_set)[1]

            if current == target_node:
                return self._reconstruct_path(came_from, current)

            # Check all 8 directions (including diagonals)
            neighbors = [
                (current[0]+1, current[1]), (current[0]-1, current[1]),
                (current[0], current[1]+1), (current[0], current[1]-1),
                (current[0]+1, current[1]+1), (current[0]-1, current[1]-1),
                (current[0]+1, current[1]-1), (current[0]-1, current[1]+1)
            ]

            for neighbor in neighbors:
                if neighbor in blocked_nodes:
                    continue

                # Diagonal moves cost slightly more (sqrt(2) ≈ 1.414)
                move_cost = 1.414 if abs(current[0]-neighbor[0]) + abs(current[1]-neighbor[1]) == 2 else 1.0
                tentative_g_score = g_score[current] + move_cost

                if tentative_g_score < g_score.get(neighbor, float('inf')):
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g_score
                    f_score[neighbor] = tentative_g_score + self.heuristic(neighbor, target_node)
                    
                    # Add to open set if not already there
                    if not any(neighbor == item[1] for item in open_set):
                        heapq.heappush(open_set, (f_score[neighbor], neighbor))

        print("[Pathfinder] No valid path found!")
        return []

    def _reconstruct_path(self, came_from, current):
        """Walks backwards from the target to build the route."""
        path = [self.to_world(current)]
        while current in came_from:
            current = came_from[current]
            path.append(self.to_world(current))
        path.reverse()
        
        # We can safely remove the very first node since the robot is already there
        if len(path) > 1:
            return path[1:]
        return path