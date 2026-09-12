import json
import argparse
import sys
import requests
from dataclasses import dataclass
from typing import Any

HELP = f"""
Amethyst is an output processor of celekli (or other data sources). This will make result of celekli.py human-readable and easier to process.
This also fetch data from teacher rating system (if required).
To use this, be sure that your celekli outputs JSON format.

If you have other data source (e.g., file stored in data.json), consider using:

{'type data.json | py amethyst.py' if sys.platform == "win32" else 'cat data.json | py amethyst.py'}
"""

######################################################
def format_table(data: list[dict[str, Any]], headers: list[str]) -> str:
    if not data:
        return "<No data>"
    lines = []
    # 表头
    lines.append("\t".join(headers))
    # 数据行
    for item in data:
        row = [str(item.get(h, "")) for h in headers]
        lines.append("\t".join(row))
    return "\n".join(lines)

def print_result(result):
    if isinstance(result, list):
        if result:
            headers = list(result[0].keys())
            print(format_table(result, headers))
        else:
            print("<No data>")
    elif isinstance(result, dict):
        for k, v in result.items():
            print(f"{k}\t{v}")
    else:
        print(result)
######################################################

# vxxq, vsksj
def translate_time(season: str, data: str) -> set[str]:
    """
    Time translation

    e.g. "秋冬" "周一第2,3节;周三第2节" -> (秋a2,秋a3,秋c2,冬a2,冬a3,冬c2), so that set can be used to check intersection
    """
    WEEKS = {
        "周一": "a", "周二": "b", "周三": "c", "周四": "d", "周五": "e", "周六": "f", "周日": "g"
    }
    SEASONS = ("春", "夏", "秋", "冬")
    if data == '' or data == '--':
        return set()

    no_duplicates = set()
    normals = set()
    for i in data.split(";"):
        contents = i.split("第")
        #print(contents)
        nums = list(map(int, "".join(filter(lambda x: x in '0123456789,', contents[1])).split(",")))
        if any((i in contents[0] for i in SEASONS)):
            weeks = WEEKS[contents[0][1:]]
            for j in nums:
                no_duplicates.add(f"{contents[0][0]}{weeks}{j}")
        else:
            weeks = WEEKS[contents[0]]
            for j in nums:
                normals.add(f"{weeks}{j}")

    for i in normals:
        for j in season:
            no_duplicates.add(f"{j}{i}")

    return no_duplicates

def redisplay(data: list[dict[str, Any]], translation: dict[str, str]) -> list[dict[str, Any]]:
    return list(map(
        lambda x: dict(
            map(
                lambda k: [k[1], x[k[0]]],
                filter(lambda s: s[0] in x , translation.items())
            )
        ), data
    ))

LESSON_TRANSLATOR = {
    "jsxm": "teacher",
    "kcdm": "code",
    "kcmc": "name",
    "vxxq": "terms",
    "xf": "credit",
    "zxs": "week_time",
    "skdd": "location",
    "vkssj": "exam_time",
    "vsksj": "time",
    "remaining": "remaining",
    "capacity": "capacity",
    "faculty_sel": "faculty_sel",
    "total_sel": "total_sel"
}

@dataclass(repr = True)
class Lesson:
    code: str
    teacher: str
    season: str
    timedata: str

def reprocess(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    global log_level
    def _rs(val: str):
        sp = val.split("/")
        return {
            "remaining": sp[0],
            "capacity": sp[1]
        }

    def _yxrs(val: str):
        sp = val.split("~")
        return {
            "faculty_sel": sp[0],
            "total_sel": sp[1]
        }

    result = []
    SPECIAL = {
        'rs': _rs, "yxrs": _yxrs
    }
    for i in data:
        origin = list(filter(lambda k: k[0] not in SPECIAL, i.items()))
        special: list[tuple[str, Any]] = []
        for j in SPECIAL:
            if log_level >= 5:
                print(f"Check {j} in {i}", file=sys.stderr)
            if j in i:
                special += SPECIAL[j](i[j]).items()
        if log_level >= 5:
            print(f"Special: {special}", file=sys.stderr)
        result.append(dict(origin + special))
    return result

def handle_chosen(chosen: list[dict[str, Any]]) -> dict[str, list[Lesson]]:
    """
    Returning: time -> [courses ...]
    """
    result = dict()
    for i in chosen:
        extraction = Lesson(i.get("kcdm", "<Unknown code>"), i.get("jsxm", "<Unknown teacher>"), i.get("vxxq", ""), i.get("vsksj", ""))
        times = translate_time(extraction.season, extraction.timedata)
        for j in times:
            if j not in result:
                result[j] = [extraction]
            else:
                result[j].append(extraction)
    return result

def main():
    global log_level
    parser = argparse.ArgumentParser("Amethyst", add_help = False)
    parser.add_argument("-h", "--help", action='store_true', help="Show help message")
    parser.add_argument("--log-level", required=False, default=0, type=int)
    parser.add_argument("-f", "--format", required=False, default="table", choices=["table", "json"], help="Output format")
    parser.add_argument("-c", "--chosen", required=False, default="", help="Provide information of classes you've chosen to help with filtering")
    parser.add_argument("-i", "--conflict", required=False, choices=["none", "remove", "detail"], help="""Show how to deal with classes conflicting with your selected courses.
                        - none: Do not consider chosen classes.
                        - remove: Final result will not contain any conflicting classes.
                        - detail: Final result will indicate what chosen classes must be removed 
                        if you want to choose one conflicting class.
""")
    parser.add_argument("-r", "--rating-network", required=False, default="Get online source of teacher rating")
    parser.add_argument("-rl", "--rating-local", required=False, default="Get offline (json) source of teacher rating")

    options = parser.parse_args()
    log_level = options.log_level

    if options.help:
        parser.print_help()
        print(HELP)
        sys.exit(0)

    # Temporary
    try:
        parsed = json.load(sys.stdin)
    except IOError, json.JSONDecodeError:
        print("Cannot parse input!", file=sys.stderr)
        sys.exit(1)

    chosen_data = []
    chosen_collection = {}
    has_chosen = False
    if options.chosen:
        try:
            with open(options.chosen, 'r') as f:
                chosen_data = json.load(f)
            chosen_collection = handle_chosen(chosen_data)
            has_chosen = True
        except (FileNotFoundError, json.JSONDecodeError, TypeError, IndexError) as e:
            print(f"Cannot parse file: {e}!", file=sys.stderr)
            sys.exit(1)

    # Temporarily
    result = redisplay(reprocess(parsed), LESSON_TRANSLATOR)    
    if has_chosen and options.conflict != "none":
        removing = []
        for idx, i in enumerate(result):
            conflict_with: list[Lesson] = []
            for j in translate_time(i["terms"], i["time"]):
                if j in chosen_collection:
                    conflict_with += chosen_collection[j]
            if options.conflict == "remove":
                if conflict_with:
                    removing.append(idx)
            elif options.conflict == "detail":
                i["conflicts"] = conflict_with
        for i in reversed(removing):
            result.pop(i)

    if options.format == "table":
        print_result(result)
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()