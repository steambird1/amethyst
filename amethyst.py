
from __future__ import annotations
import json
import argparse
import sys
import os
import datetime
import copy
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import requests

HAS_REQUESTS: bool = False
try:
    import requests
    HAS_REQUESTS = True
except ImportError as e:
    pass

HELP = f"""

Note:
If none of the rating options is given, the system will not fetch ratings.

Amethyst is an output processor of celekli (or other data sources). This will make result of celekli.py human-readable and easier to process.
This also fetch data from teacher rating system (if required).
To use this, be sure that your celekli outputs JSON format.

If you have other data source (e.g., file stored in data.json), consider using:

{'type data.json | py amethyst.py' if sys.platform == "win32" else 'cat data.json | py amethyst.py'}

{'''
Warning: "requests" is not detected in your python environment. Without this, amethyst can still run, but network
functions are not available. You may not use online teacher rating references. Consider fixing this by running:

pip install requests
''' if not HAS_REQUESTS else ''}
"""

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
CACHE_PATH = os.path.join(os.path.abspath('.'), 'amethyst_cache.json')

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
    "total_sel": "total_sel",
    "teacher": "teacher",
    "location": "location"
}

AUTO_OPTIONS = {
    "chalaoshi.xhuya.cn": "b",
    "chalaoshi.netlify.app": "n"
}

@dataclass
class Teacher:

    @dataclass
    class GradeInfo:
        mean: float
        dev: float | None = None

    name: str
    college: str
    rating: float
    grades: dict[str, Teacher.GradeInfo]
    update_time: str
    risk_flags: str = ''

    def is_same(self, other: Teacher):
        return (self.name, self.college) == (other.name, other.college)

    def is_be_replaced(self, other: Teacher):
        if self.risk_flags and (not other.risk_flags):
            return True
        elif (not self.risk_flags) and other.risk_flags:
            return False
        else:
            return self.updated_at() < other.updated_at()

    def updated_at(self):
        return datetime.datetime.strptime(self.update_time, DATETIME_FORMAT)

    def to_dict(self):
        return {
            "name": self.name,
            "college": self.college,
            "score": self.rating,
            "courses": list(
                map(
                    lambda x: {
                        "name": x[0],
                        "gpa": x[1].mean,
                        "dev": x[1].dev
                    },
                    self.grades.items()
                )
            ),
            "update_time": self.update_time,
            "risk_flags": self.risk_flags
        }

@dataclass(frozen = True)
class TeacherRequest:
    name: str
    class_hint: str

type ResolvesRet = list[Teacher]

_curr_time_str = lambda: datetime.datetime.now().strftime(DATETIME_FORMAT)

def _float(x: str) -> float:
    try:
        return float(x)
    except ValueError:
        return 0

def _courses_to_dict(courses: list[dict[str, Any]]) -> dict[str, Teacher.GradeInfo]:
    return dict(map(lambda x: (x["name"], Teacher.GradeInfo(float(x["gpa"]), float(x["dev"]) if x.get("dev") is not None else None)), courses)) 

def _raw_to_teachers(data: Any, update_at: str | None = None) -> ResolvesRet:
    altn = datetime.datetime.now().strftime(DATETIME_FORMAT)
    return list(map(
        lambda x: Teacher(x["name"], x["college"], _float(x["score"]), _courses_to_dict(x["courses"]), 
                          update_at if update_at is not None else x.get("update_at", altn)), data
    ))

def _merge_lists(a: list[Teacher], b: list[Teacher]) -> list[Teacher]:
    if len(a) > len(b):
        return _merge_lists(b, a)
    result = copy.deepcopy(a)
    bref: dict[tuple[str, str], Teacher] = {}
    aref: set[tuple[str, str]] = set()
    for i in a:
        aref.add((i.name, i.college))
    for i in b:
        bref[(i.name, i.college)] = i
    for idx, i in enumerate(result):
        bcur = bref.get((i.name, i.college))
        if bcur:
            if i.is_be_replaced(bcur):
                result[idx] = bcur
    for i in b:
        if (i.name, i.college) not in aref:
            result.append(i)
    return result

curr_caches: list[Teacher] = []

def _check_ambiguity(data: Any, requested: set[TeacherRequest]):
    request_names = set(map(lambda x: x.name, requested))
    data_names = set()
    ambiguous_names = set()
    for i in data:
        name = i["name"]
        if name in data_names:
            ambiguous_names.add(name)
        else:
            data_names.add(name)
    request_names.intersection_update(data_names - ambiguous_names)
    return request_names

def _resolver_b_online(url: str, requested: set[TeacherRequest]) -> ResolvesRet:
    global curr_caches, show_net_detail

    if not HAS_REQUESTS:
        raise NotImplementedError("Cannot execute resolver without 'requests'")
    f_teachers: list[Teacher] = []
    update_at = _curr_time_str()
    
    for idxi, i in enumerate(requested):
        req = requests.get(f"https://{url}/api/search", params={'q': i.name})
        if show_net_detail:
            print(f"Requesting teacher {i.name}... ({idxi}/{len(requested)})", file=sys.stderr)
        rj = req.json()
        if "teachers" not in rj:
            continue
        teacher = rj["teachers"]
        request_names = _check_ambiguity(teacher, requested)
        for idx, j in enumerate(teacher):
            creq = requests.get(f"https://{url}/api/teacher/{j["tid"]}")
            if show_net_detail:
                print(f"Requesting teacher detail of {i.name}... ({idx}/{len(teacher)})", file=sys.stderr)
            cdata = creq.json()
            if any((i not in cdata for i in ('courses', 'score'))):
                continue
            courses: list[dict[str, Any]] = cdata["courses"]
            if j["name"] in request_names or any((i.class_hint.strip() == l["name"].strip() for l in courses)):
                cldict = _courses_to_dict(courses)
                f_teachers.append(Teacher(i.name, j["college"], cdata["score"], cldict, update_at))
    #curr_caches = _merge_lists(curr_caches, f_teachers)
    store_cache(f_teachers)
    return f_teachers

def _resolver_b_offline(data: Any, requested: set[TeacherRequest]) -> ResolvesRet:
    """
    Data format:
    [
        {name, college, rating, {grades...}}...
    ]
    """
    update_at = _curr_time_str()
    request_names = _check_ambiguity(data, requested)
    return _raw_to_teachers(filter(
                lambda t: (t["name"] in request_names)
                 or any((TeacherRequest(t["name"], i["name"]) in requested for i in t["courses"])),
                data
            ), update_at)

def _resolver_n_online(url: str, requested: set[TeacherRequest]) -> ResolvesRet:
    if not HAS_REQUESTS:
        raise NotImplementedError("Cannot execute resolver without 'requests'")
    tcsv = requests.get(f"https://{url}/cls/teachers.csv")
    tdata = []
    for i in tcsv.text.splitlines():
        ispl = i.split(",")
        tdata.append({
            "name": ispl[1],
            "college": ispl[2],
            "score": _float(ispl[5])
        })
    rdata = requests.get(f"https://{url}/cls/gpa.json").json()
    return _resolver_n_offline({
        "teachers": tdata, "ratings": rdata
    }, requested)

def _resolver_n_offline(data: Any, requested: set[TeacherRequest]) -> ResolvesRet:
    """
    Note: if a teacher appears more than once, then
    - The information will be warned
    - The classes & subjects & faculties will be merged
    """
    tc_ref: dict[str, Teacher] = {}
    updated_at = _curr_time_str()
    dt, dr = data["teachers"], data["ratings"]
    request_name = _check_ambiguity(dt, requested)
    for i in dt:
        if i["name"] in tc_ref:
            tc_ref[i["name"]].risk_flags = 'ambiguous'
            tc_ref[i["name"]].college += f"|{i['college']}"
            tc_ref[i["name"]].rating = max(tc_ref[i["name"]].rating, i["score"])
        else:
            tc_ref[i["name"]] = Teacher(i["name"], i["college"], i["score"], {}, updated_at)
    for i in dr:
        if i not in tc_ref:
            continue
        tc_ref[i].grades = dict(
            map(lambda x: (x[0], Teacher.GradeInfo(_float(x[1]), _float(x[3]))), dr[i])
        )
    conclude = list(map(lambda x: tc_ref[x], tc_ref))
    store_cache(conclude)
    result = list(filter(lambda x: (x.name in request_name) or
                         any((TeacherRequest(x.name, i) in requested for i in x.grades)), conclude))
    return result

def _resolver_auto_online(url: str, requested: set[TeacherRequest]) -> ResolvesRet:
    if url in AUTO_OPTIONS:
        return RESOLVER[AUTO_OPTIONS[url]][0](url, requested)
    else:
        raise NotImplementedError(f"Format of {url} is unknown")

def _resolver_auto_offline(data: Any, requested: set[TeacherRequest]) -> ResolvesRet:
    formats = data.get("format")
    if formats in AUTO_OPTIONS:
        return RESOLVER[AUTO_OPTIONS[formats]][1](data, requested)
    else:
        raise NotImplementedError(f"Cannot get format information from data input")

RESOLVER = {
    "b": (_resolver_b_online, _resolver_b_offline),
    "n": (_resolver_n_online, _resolver_n_offline),
    "auto": (_resolver_auto_online, _resolver_auto_offline)
}

def store_cache(data: list[Teacher]):
    global log_level
    if no_caching:
        return
    raw_data = []
    try:
        with open(CACHE_PATH, "r") as f:
            raw_data = json.load(f)
    except FileNotFoundError, IOError, json.JSONDecodeError:
        pass
    cached_data: list[Teacher] = _merge_lists(_raw_to_teachers(raw_data), data)
    finale = list(map(lambda x: x.to_dict(), cached_data))
    if log_level >= 10:
        print(f"[*] Attempt to cache: {data}", file=sys.stderr)
        print(f"[*] Finale: {finale}", file=sys.stderr)
    with open(CACHE_PATH, "w") as f:
        json.dump(finale, f, ensure_ascii=False, indent=2)

def load_cache(requested: set[TeacherRequest]) -> ResolvesRet:
    """
    Cache is loaded in B-format.
    """
    with open(CACHE_PATH, "r") as f:
        data = json.load(f)
        return _resolver_b_offline(data, requested)

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

    def _jsxm(val: str):
        return {
            "teacher": ",".join(val.split("/")[0].split("<br>"))
        }

    def _skdd(val: str):
        return {
            "location": ",".join(val.split("<br>"))
        }

    result = []
    SPECIAL = {
        'rs': _rs, "yxrs": _yxrs, "jsxm": _jsxm, "skdd": _skdd
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
    global log_level, no_caching, show_net_detail
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
    rating_group = parser.add_mutually_exclusive_group()
    rating_group.add_argument("-r", "--rating-network", required=False, default='', help="Get online source of teacher rating")
    rating_group.add_argument("-rl", "--rating-local", required=False, default='', help="Get offline (json) source of teacher rating")
    rating_group.add_argument("-rc", "--rating-cache", required=False, action='store_true', help="Get rating content from cache")
    rating_group.add_argument("-rn", "--rating-none", required=False, action='store_true', help="Do not get rating")
    parser.add_argument("--no-cache", required=False, action='store_true', help="Do not cache web download")
    parser.add_argument("-df", "--data-format", required=False, choices=["b", "n", "auto"], default='auto', help="Specify data format.")
    parser.add_argument("--show-networking", required=False, action='store_true', help="Show network details")
    parser.add_argument("-ft", "--full-teacher-details", required=False, action='store_true', help="Provide full information if a class is presented by multiple teachers. If not provided, only the average score of the teachers, average GPA report and maximum GPA fluctuation will be output.")
    parser.add_argument("-w", "--ignore-warning", required=False, action='store_true', help="Ignore warnings in data processing.")

    options = parser.parse_args()
    log_level = options.log_level
    show_net_detail = options.show_networking

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

    # Consider teacher ratings
    no_caching = options.no_cache
    if options.rating_network or options.rating_local or options.rating_cache:
        rating_demand = set()

        for i in result:
            for j in i["teacher"].split(","):
                rating_demand.add(TeacherRequest(j, i["name"]))
        if log_level >= 2:
            print(f"Demanded: {rating_demand}", file=sys.stderr)

        resolved: ResolvesRet = []

        def _load_ratings():
            nonlocal resolved
            print("Loading ratings...", file=sys.stderr)
            if options.rating_network:
                resolved = RESOLVER[options.data_format][0](options.rating_network, rating_demand)
            elif options.rating_local:
                resolved = RESOLVER[options.data_format][1](options.rating_local, rating_demand)
            elif options.rating_cache:
                resolved = load_cache(rating_demand)

        if log_level >= 30:
            _load_ratings()
        else:
            try:
                _load_ratings()
            except Exception as e:
                print(f"ERROR: Unable to fetch rating information: {e}", file=sys.stderr)

        # In the future, consider adding a function supporting overall assessment of relevant teachers.
        # currently we discard irrelevant classes.
        collected: dict[TeacherRequest, tuple[Teacher.GradeInfo, Teacher]] = {}
        for i in resolved:
            for j in i.grades:
                rq = TeacherRequest(i.name, j)
                if rq in rating_demand:
                    collected[rq] = (i.grades[j], i)

        if log_level >= 2:
            print(f"Collected: {collected}", file=sys.stderr)

        for i in result:

            def _process(lst):
                result = []
                for i in lst:
                    if i is None:
                        result.append(0)
                    elif isinstance(i, int) or isinstance(i, float):
                        result.append(i)
                    elif isinstance(i, str):
                        try:
                            result.append(float(i))
                        except:
                            result.append(0)
                    else:
                        result.append(0)
                return result

            def _actual_len(lst):
                return sum(map(lambda x: 0 if x is None else 1, lst))

            def _present_warning(txt):
                nonlocal options
                if not options.ignore_warning:
                    print(f"WARNING: {txt}", file=sys.stderr)

            teacher_list = i["teacher"].split(",")
            grade_avgs = []
            grade_devs = []
            ratings = []
            for j in teacher_list:
                rq = TeacherRequest(j, i["name"])
                if log_level >= 3:
                    print(f"Requested: {rq}", file=sys.stderr)
                if rq in collected:
                    grade_avgs.append(collected[rq][0].mean)
                    grade_devs.append(collected[rq][0].dev)
                    ratings.append(collected[rq][1].rating)
            gavg = _actual_len(grade_avgs)
            glen = _actual_len(ratings)
            if not all((grade_avgs, grade_devs, ratings)):
                _present_warning(f"Unable to get rating of class {i["name"]} of {i["teacher"]}")
            elif not all((gavg, glen)):
                _present_warning(f"Incomplete data of class {i["name"]} of {i["teacher"]}")
            else:
                if log_level >= 2:
                    print(f"{grade_avgs},{grade_devs},{ratings}", file=sys.stderr)
                i["grade_avg"] = sum(_process(grade_avgs)) / gavg if gavg != 0 else None
                i["grade_dev"] = max(_process(grade_devs))
                i["rating"] = sum(_process(ratings)) / glen if glen != 0 else None
                if options.full_teacher_details:
                    i["grades"] = grade_avgs
                    i["grade_devs"] = grade_devs
                    i["ratings"] = ratings
        
    elif not options.rating_none:
        print("WARNING: No rating option is given. By default, amethyst will not add any rating data. To suppress this warning, use -rn or --rating-none.", file=sys.stderr)

    if options.format == "table":
        print_result(result)
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()