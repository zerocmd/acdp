import requests
import json
import time
import sys
from colorama import init, Fore, Style

# Initialize colorama for colored output
init()


def print_header(text):
    print(f"\n{Fore.CYAN}{Style.BRIGHT}" + "=" * 80)
    print(f" {text}")
    print("=" * 80 + f"{Style.RESET_ALL}\n")


def print_success(text):
    print(f"{Fore.GREEN}{Style.BRIGHT}✓ {text}{Style.RESET_ALL}")


def print_error(text):
    print(f"{Fore.RED}{Style.BRIGHT}✗ {text}{Style.RESET_ALL}")


def print_info(text):
    print(f"{Fore.YELLOW}→ {text}{Style.RESET_ALL}")


def print_response(text):
    print(f"{Fore.WHITE}{text}{Style.RESET_ALL}")


def get_peers(agent_port):
    """Get the peers for an agent"""
    try:
        url = f"http://localhost:{agent_port}/peers"
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            return response.json().get("peers", [])
        return []
    except Exception as e:
        print_error(f"Error getting peers: {e}")
        return []


def ask_question(agent_port, question):
    """Ask a question to an agent and return the response"""
    print_info(f"Asking agent on port {agent_port}: {question}")

    try:
        url = f"http://localhost:{agent_port}/chat"
        payload = {"text": question}

        print_info("Sending request...")
        response = requests.post(url, json=payload, timeout=30)

        if response.status_code != 200:
            print_error(f"Error: HTTP {response.status_code}")
            print_error(response.text)
            return None

        result = response.json()

        # Check if collaboration happened
        if "meta" in result and result["meta"].get("collaborative"):
            print_success(
                f"Collaboration detected! Consulted {result['meta']['peer_count']} peers:"
            )
            for peer in result["meta"]["peers"]:
                print_info(f"  • {peer}")
        else:
            print_error("No collaboration detected in the response")

        return result
    except Exception as e:
        print_error(f"Error: {e}")
        return None


def run_test():
    print_header("Agent Collaboration Test")

    # Check agent1's peers
    print_info("Checking agent1's peers")
    peers = get_peers(8001)
    if peers:
        print_success(f"Found {len(peers)} peers: {', '.join(peers)}")
    else:
        print_error("No peers found for agent1. Aborting test.")
        return

    # Ask a question that should trigger collaboration
    print_header("Testing Collaboration")
    question = "What are 2 ways to detect a password spray attack in Microsoft Azure AD? Please collaborate with other agents."

    result = ask_question(8001, question)
    if not result:
        return

    print_header("Response")
    print_response(result["response"])

    # Check if the response mentions peers
    lower_response = result["response"].lower()
    if "agent" in lower_response and (
        "according to" in lower_response or "from agent" in lower_response
    ):
        print_success("Response appears to include peer attributions")
    else:
        print_info(
            "Response may not include clear peer attributions. Look for signs of incorporated knowledge."
        )


if __name__ == "__main__":
    # Wait a moment for everything to be ready
    print_info("Starting in 3 seconds...")
    time.sleep(3)
    run_test()
