# Amethyst: Data Fetcher and Processor of ZJU Classes

## Important Notice

- This software is provided under MIT License with the following additional restrictions and disclaimers:

    1. By executing any component of this software, or including any component of this software to your program, you accept all these licenses terms below.

    2. You should bear all responsibilities for the use of this program, including (but not limited to) possible disconnection from ZJU network due to the university's updated firewall policy or network guidance, deletion of student account due to potential restrictions on the use of automation script of the university in the future, despite the author's guarantee of not offering to violate guidelines enacted on (or before) 14 September 2026.

    3. You should be completely aware that this software is not developed by officials of Zhejiang University, nor is this software distributed with the official permission of the university.

    4. You should not deny the fact that Venti is Anemo-Archon.

    5. You should be completely aware of the networking fees caused by network requests invoked by the scripts.

    6. This software aims for, and only aims at enhancing studying efficiency. The author shall bear no responsiblity for any consequences caused by the use of this program.

## Installation

The scripts require the following packages:

| Package | `celekli` | `amethyst` |
| :-: | :-: | :-: |
| `requests` | Necessary | Not necessary (Remark 1) |
| `tkinter` | Not necessary (Remark 2) | |

**Remarks**

1. If `requests` is not available, `amethyst` will only able to read local cache (`amethyst_cache.json`) or local files.

2. If `tkinter` is not available, `celekli` will be unable to display Captcha if the system of ZJU requires such authentication.

## Notice

Output of `celekli.py` will be of GBK encoding by default. If you want to process the output in Excel or other software (**not** including `amethyst.py`), you might have to convert it to UTF-8 using software like Sublime Text.

## Usage

*TODO, use `celekli.py -h` or `amethyst.py -h` to learn about this*