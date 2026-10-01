import requests
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


def test_assist_endpoint(port, agent_name):
    """Test if the assist endpoint is working"""
    url = f"http://localhost:{port}/assist"
    test_data = {
        "question": "What is machine learning?",
        "requestor_id": "test-script",
        "requestor_name": "Test Script",
        "timestamp": time.time(),
    }

    try:
        print_info(f"Testing assist endpoint for {agent_name} on port {port}...")
        response = requests.post(url, json=test_data)

        if response.status_code == 200:
            print_success(f"Assist endpoint is working for {agent_name}!")
            response_data = response.json()
            if "response" in response_data:
                print_info(f"Response snippet: {response_data['response'][:100]}...")
            return True
        else:
            print_error(f"Assist endpoint returned status code {response.status_code}")
            print_error(f"Response: {response.text}")
            return False
    except Exception as e:
        print_error(f"Error testing assist endpoint: {e}")
        return False


def main():
    print_header("Agent Assist Endpoint Verification")

    # Add more agents to test here
    agents = [
        {"port": 8003, "name": "Agent Zero"},
        {"port": 8001, "name": "Agent One"},
        {"port": 8002, "name": "Agent Two"},
        {"port": 8004, "name": "Agent Four"},
    ]

    failing_agents = []

    for agent in agents:
        if not test_assist_endpoint(agent["port"], agent["name"]):
            failing_agents.append(agent)

    if failing_agents:
        print_header("Summary - Issues Found")
        print_error(f"The following agents have issues with their assist endpoints:")
        for agent in failing_agents:
            print_error(f"  • {agent['name']} on port {agent['port']}")

        print_info("\nPossible fixes:")
        print_info("1. Make sure all agents have been updated with the latest code")
        print_info(
            "2. Check if the /assist endpoint is properly implemented in all agents"
        )
        print_info("3. Ensure agents are running and accessible on the specified ports")
    else:
        print_header("All Assist Endpoints Working!")
        print_success("All agents have working assist endpoints.")
        print_info("\nYou can now test collaboration between agents.")


if __name__ == "__main__":
    main()
