from langgraph import StateGraph, START, END
from .nodes_and_states import RobotState, perception_node, arbiter_node, director_node, navigator_node, executor_node


def build_robot_graph():
    workflow = StateGraph(RobotState)

    # Add Nodes
    workflow.add_node("perception", perception_node)
    workflow.add_node("arbiter", arbiter_node)
    workflow.add_node("director", director_node)
    workflow.add_node("navigator", navigator_node)
    workflow.add_node("executor", executor_node)

    # Define Edges
    workflow.add_edge(START, "perception")
    workflow.add_edge("perception", "arbiter")

    # Conditional Routing Logic
    def route_after_arbiter(state: RobotState):
        if state.get("evading"):
            return END  # Skip cognitive loop if dodging a wall

        status = state["blackboard"].state["mission"]["status"]
        if status == "needs_objectives":
            return "director"
        elif status == "needs_planning":
            return "navigator"
        elif status == "executing":
            return "executor"
        else:
            return END

    workflow.add_conditional_edges("arbiter", route_after_arbiter)

    # Sequential Cognitive Flow
    # After getting objectives, plan them
    workflow.add_edge("director", "navigator")
    workflow.add_edge("navigator", "executor")  # After planning, execute them
    workflow.add_edge("executor", END)         # End of tick

    return workflow.compile()
