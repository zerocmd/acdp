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


def ask_question(question):
    """Ask a question to an agent and wait for the response"""
    print_info(f"Asking question: {question}")

    try:
        url = "http://localhost:8001/chat"
        payload = {"text": question}

        print_info(
            "Sending request (this might take up to 30 seconds due to increased timeout)..."
        )
        response = requests.post(url, json=payload, timeout=60)

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


def main():
    print_header("Testing Agent Collaboration with Increased Timeout")

    # Define a question that requires collaboration
    question = "What are two ways to detect a password spray attack in Microsoft Azure AD? Please collaborate with other agents."

    # Ask the question
    result = ask_question(question)

    if result:
        print_header("Response")
        print(result["response"])


if __name__ == "__main__":
    # Wait for containers to start up
    print_info("Waiting for containers to be ready...")
    time.sleep(5)
    main()
