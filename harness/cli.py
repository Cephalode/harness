"""Rich-based interactive chat CLI with slash commands."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from .config import load_config, validate_config
from .events import DashboardRelay, EventBus
from .expertise import ExpertiseManager
from .models import CostTracker
from .orchestrator import Orchestrator
from .session import Session
from .state import StateStore


console = Console()
error_console = Console(stderr=True)


class HarnessCLI:
    """Interactive chat CLI for the multi-team agentic harness."""

    def __init__(self, config_path: str = "configs/multi_team.yaml") -> None:
        self.config_path = config_path
        self.show_workers = False
        self.orchestrator: Orchestrator | None = None
        self.session: Session | None = None
        self.base_dir = str(Path(config_path).parent.parent.resolve())
        self._event_bus: EventBus | None = None
        self._relay: DashboardRelay | None = None

    def _load(self) -> None:
        """Load configuration and initialize orchestrator."""
        try:
            config = load_config(self.config_path)
        except FileNotFoundError:
            error_console.print(f"[red]Config not found: {self.config_path}[/red]")
            error_console.print("Run from the harness project root directory.")
            sys.exit(1)

        warnings = validate_config(config)
        for w in warnings:
            console.print(f"[yellow]⚠ {w}[/yellow]")

        cost_tracker = CostTracker()
        self.session = Session(sessions_dir=str(Path(self.base_dir) / "sessions"))
        self._state_store = StateStore(state_dir=str(Path(self.base_dir) / "state"))
        asyncio.run(self._state_store.init())
        self._event_bus = EventBus(state_store=self._state_store)
        self.orchestrator = Orchestrator(
            config=config,
            cost_tracker=cost_tracker,
            session=self.session,
            event_bus=self._event_bus,
            state_store=self._state_store,
        )
        # Start the relay (non-blocking, fails gracefully if dashboard not running)
        self._relay = DashboardRelay(self._event_bus)
        console.print(f"[green]✓[/green] Loaded config: {len(self.orchestrator.teams)} teams")
        console.print(f"[green]✓[/green] Session: {self.session.session_id}")

    def _print_banner(self) -> None:
        """Print welcome banner."""
        banner = Text()
        banner.append("Multi-Team Agentic Coding Harness", style="bold cyan")
        banner.append("\n")
        banner.append("Type your message to start. Use ", style="dim")
        banner.append("/help", style="bold")
        banner.append(" for commands.", style="dim")
        console.print(Panel(banner, border_style="cyan"))
        console.print()

    def _print_help(self) -> None:
        """Print available commands."""
        table = Table(title="Commands", show_header=False, border_style="dim")
        table.add_column("Command", style="bold cyan")
        table.add_column("Description")
        commands = [
            ("/toggle workers", "Show/hide detailed worker activity"),
            ("/cost", "Show cost breakdown"),
            ("/teams", "Show team structure"),
            ("/expertise [agent]", "Show an agent's expertise/mental model"),
            ("/compact", "Compress conversation history"),
            ("/clear", "Clear conversation"),
            ("/commands", "List available command workflows"),
            ("/help", "Show this help"),
            ("/quit", "Exit the harness"),
        ]
        for cmd, desc in commands:
            table.add_row(cmd, desc)
        console.print(table)

    def _handle_command(self, user_input: str) -> bool:
        """Handle a slash command. Returns True if handled, False if it's a regular message."""
        parts = user_input.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "/help":
            self._print_help()
            return True

        elif cmd == "/quit" or cmd == "/exit":
            console.print("[dim]Goodbye![/dim]")
            raise SystemExit(0)

        elif cmd == "/toggle":
            self.show_workers = not self.show_workers
            state = "ON" if self.show_workers else "OFF"
            console.print(f"[cyan]Worker detail view: {state}[/cyan]")
            if self.show_workers and self.orchestrator:
                console.print(self.orchestrator.get_team_info())
            return True

        elif cmd == "/cost":
            if self.orchestrator:
                console.print(Markdown(self.orchestrator.get_cost_summary()))
            else:
                console.print("[yellow]No session active[/yellow]")
            return True

        elif cmd == "/teams":
            if self.orchestrator:
                console.print(self.orchestrator.get_team_info())
            else:
                console.print("[yellow]No session active[/yellow]")
            return True

        elif cmd == "/expertise":
            if not self.orchestrator:
                console.print("[yellow]No session active[/yellow]")
                return True

            em = ExpertiseManager(self.base_dir)
            if arg:
                # Show specific agent's expertise
                configs = []
                # Check all agents
                for agent_cfg in [self.orchestrator.config.orchestrator] + [
                    t.lead for t in self.orchestrator.config.teams
                ] + [w for t in self.orchestrator.config.teams for w in t.workers]:
                    if agent_cfg.name == arg:
                        configs = agent_cfg.expertise
                        break
                if configs:
                    content = em.format_expertise_section(configs)
                    if content:
                        console.print(Panel(Markdown(content), title=f"Expertise: {arg}", border_style="green"))
                    else:
                        console.print(f"[yellow]No expertise data for {arg} yet[/yellow]")
                else:
                    names = em.get_agent_names()
                    console.print(f"[yellow]Agent '{arg}' not found. Available: {', '.join(names) or 'none'}[/yellow]")
            else:
                # List all expertise files
                names = em.get_agent_names()
                if names:
                    console.print("[bold]Agents with expertise files:[/bold]")
                    for name in names:
                        console.print(f"  - {name}")
                else:
                    console.print("[yellow]No expertise files yet[/yellow]")
            return True

        elif cmd == "/compact":
            if self.session:
                self.session.compact()
                console.print("[green]✓ Conversation history compacted[/green]")
            return True

        elif cmd == "/clear":
            if self.session:
                self.session.clear()
                console.print("[green]✓ Conversation cleared[/green]")
            return True

        elif cmd == "/commands":
            if self.orchestrator:
                cmds = self.orchestrator.config.commands
                if cmds:
                    for name, cmd_cfg in cmds.items():
                        console.print(f"  [cyan]{name}:[/cyan] {cmd_cfg.description}")
                else:
                    console.print("[yellow]No command workflows configured[/yellow]")
            else:
                console.print("[yellow]No session active[/yellow]")
            return True

        return False

    async def _process_message(self, user_input: str) -> None:
        """Process a user message through the orchestrator."""
        if not self.orchestrator:
            console.print("[red]No orchestrator loaded[/red]")
            return

        # Start the relay for this processing cycle
        relay_started = False
        if self._relay:
            try:
                await self._relay.start()
                relay_started = True
            except Exception:
                pass  # Dashboard not running — that's fine

        try:
            with console.status("[bold cyan]Orchestrating...[/bold cyan]", spinner="dots"):
                response = await self.orchestrator.process_message(user_input)

            # Display response
            console.print()
            console.print(Panel(
                Markdown(response),
                title="[bold]Orchestrator[/bold]",
                border_style="blue",
            ))

            # Show cost footer
            cost = self.orchestrator.cost_tracker.total_cost
            usage = self.orchestrator.cost_tracker.total_usage
            console.print(
                f"[dim]Cost: ${cost:.4f} | "
                f"Tokens: {usage.input_tokens:,} in / {usage.output_tokens:,} out[/dim]"
            )
            console.print()
        finally:
            if relay_started and self._relay:
                await self._relay.stop()

    def run(self) -> None:
        """Main CLI loop."""
        self._load()
        self._print_banner()

        while True:
            try:
                user_input = Prompt.ask("[bold cyan]You[/bold cyan]")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye![/dim]")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Check for slash commands
            if user_input.startswith("/"):
                try:
                    if self._handle_command(user_input):
                        continue
                except SystemExit:
                    break

            # Process as a regular message
            try:
                asyncio.run(self._process_message(user_input))
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted[/yellow]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")


def main() -> None:
    """Entry point for the CLI."""
    import argparse

    parser = argparse.ArgumentParser(description="Multi-Team Agentic Coding Harness")
    parser.add_argument(
        "-c", "--config",
        default="configs/multi_team.yaml",
        help="Path to config file (default: configs/multi_team.yaml)",
    )
    parser.add_argument(
        "-d", "--dashboard",
        action="store_true",
        help="Launch the web dashboard instead of the interactive CLI",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Dashboard host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5173,
        help="Dashboard port (default: 5173)",
    )
    args = parser.parse_args()

    if args.dashboard:
        from .dashboard import run_dashboard
        console.print(Panel(
            f"[bold green]Harness Dashboard[/]\n"
            f"Config: {args.config}\n"
            f"URL:    http://{args.host}:{args.port}",
            border_style="green",
        ))
        run_dashboard(config_path=args.config, host=args.host, port=args.port)
    else:
        cli = HarnessCLI(config_path=args.config)
        cli.run()


if __name__ == "__main__":
    main()
