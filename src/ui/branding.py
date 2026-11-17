"""Large, hand-drawn ASCII branding; no fonts or terminal escapes required."""

ASCII_MARK = r"""      .##################################.
    .####'                            '####.
   ####                                  ####
   ###                                    ###
   ###                                    ###  .######.
   ###              ##########                ##      ##
   ###            ####                         '######'
   ###          ####                        //
   ###        ####                        //
   ###       ####      .######.         //
   ###       ###      ##      ##======<
   ###       ####      '######'         \\
   ###        ####                        \\
   ###          ####                        \\
   ###            ####                         .######.
   ###              ##########                ##      ##
   ###                                    ###  '######'
   ###                                    ###
   ####                                  ####
    '####.                            .####'
      '##################################'
                      ####
                ################"""

ASCII_WORDMARK = r""" ____             _     ____
|  _ \  ___   ___| | __/ ___|  ___ _ __ ___  ___ _ __
| | | |/ _ \ / __| |/ /\___ \ / __| '__/ _ \/ _ \ '_ \
| |_| | (_) | (__|   <  ___) | (__| | |  __/  __/ | | |
|____/ \___/ \___|_|\_\|____/ \___|_|  \___|\___|_| |_|"""


def console_banner(version: str, width: int = 80) -> str:
    """Keep the artwork intact; use a text header when it cannot fit."""
    lines = ASCII_WORDMARK.splitlines()
    banner_width = max(map(len, lines + ASCII_MARK.splitlines()))
    if width < banner_width:
        return f"DockScreen v{version}"
    mark = ASCII_MARK.splitlines()
    mark_width = max(map(len, mark))
    inset = " " * ((banner_width - mark_width) // 2)
    subtitle = f"MOLECULAR DOCKING / v{version}"
    return "\n".join(
        [*(inset + line for line in mark), "", *lines, "",
         subtitle.center(banner_width).rstrip()]
    )
