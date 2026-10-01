import time
import requests
import datetime
import os
import sys
from colorama import init, Fore, Style

# Initialize colorama
init()


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


# Add agent URLs here to monitor them during testing
def monitor_agents():
    agent_urls = [
        "http://localhost:8001/metadata",
        "http://localhost:8002/metadata",
        "http://localhost:8003/metadata",
        "http://localhost:8004/metadata",
    ]

    agent_info = []

    for url in agent_urls:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                info = response.json()
                agent_info.append(
                    {
                        "id": info["id"],
                        "name": info["name"],
                        "capabilities": info["capabilities"],
                        "url": url.replace("/metadata", ""),
                    }
                )
        except Exception as e:
            print(f"Error connecting to {url}: {e}")

    return agent_info


def main():
    print(f"{Fore.CYAN}Agent Collaboration Monitor{Style.RESET_ALL}")
    print("Press Ctrl+C to exit\n")

    recent_events = []

    try:
        while True:
            clear_screen()
            print(f"{Fore.CYAN}Agent Collaboration Monitor{Style.RESET_ALL}")
            print("Press Ctrl+C to exit\n")

            # Show online agents
            agents = monitor_agents()
            print(f"{Fore.GREEN}Active Agents:{Style.RESET_ALL}")
            for agent in agents:
                print(f"  • {agent['name']} ({agent['id']})")
                print(f"    Capabilities: {', '.join(agent['capabilities'])}")

            # Check for recent collaboration events (this is a simple simulation)
            # In a real implementation, this could poll a collaboration event log endpoint
            try:
                for agent in agents:
                    response = requests.get(f"{agent['url']}/gossip/stats", timeout=2)
                    if response.status_code == 200:
                        stats = response.json()
                        if stats.get("peers_received", 0) > 0:
                            event = {
                                "timestamp": datetime.datetime.now(),
                                "agent": agent["name"],
                                "event": f"Received information from {stats.get('peers_received', 0)} peers",
                            }
                            recent_events.append(event)
            except Exception as e:
                pass

            # Show recent events
            print(f"\n{Fore.YELLOW}Recent Collaboration Events:{Style.RESET_ALL}")
            if not recent_events:
                print("  No events detected yet...")
            else:
                # Show last 10 events
                for event in recent_events[-10:]:
                    time_str = event["timestamp"].strftime("%H:%M:%S")
                    print(f"  [{time_str}] {event['agent']}: {event['event']}")

            time.sleep(5)

    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()
