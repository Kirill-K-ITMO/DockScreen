"""Rich console messages and the application banner."""


from rich.console import Console

from src.ui.streams import configure_streams
configure_streams()

# Global Rich console
console = Console()

def print_header(title: str, subtitle: str = None, color: str = "cyan"):
    """
    Print a formatted header.
    
    Args:
        title: Title
        subtitle: Subtitle
        color: Header color
    """
    console.print(f"\n[bold {color}]{title}[/bold {color}]")
    if subtitle:
        console.print(subtitle, style="dim", markup=False)

def print_success(message: str):
    """
    Print a success message.
    
    Args:
        message: Message
    """
    console.print(f"[green]✓[/green] {message}")

def print_error(message: str):
    """
    Print an error message.
    
    Args:
        message: Message
    """
    console.print(f"[red]✗[/red] {message}")

def print_warning(message: str):
    """
    Print a warning.
    
    Args:
        message: Message
    """
    console.print(f"[yellow]⚠[/yellow] {message}")

def print_info(message: str):
    """
    Print an informational message.
    
    Args:
        message: Message
    """
    console.print(f"[blue]ℹ[/blue] {message}")


def print_app_header():
    from src.version import __version__
    from src.ui.branding import console_banner
    console.print(console_banner(__version__, width=console.width),
                  style="bold green", markup=False, highlight=False, no_wrap=True)
    console.print("SMILES preparation and batch molecular docking",style="dim")

def print_section_divider(title: str = None):
    """
    Print a section separator.
    
    Args:
        title: Section title
    """
    if title:
        console.print(title, style="bold cyan", markup=False)

