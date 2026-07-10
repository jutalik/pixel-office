"""Company Layer Phase 3 — evidence-first self-learning + competency."""
from pixel_office.company.employee import Employee, Team
from pixel_office.company.learning import EmployeeMemory, Lesson
from pixel_office.company.runtime import OrgRuntime, Task, TaskResult


def test_competency_insufficient_evidence_below_floor():
    m = EmployeeMemory("e1")
    m.record("task_done", "backend", ok=True)
    m.record("task_done", "backend", ok=True)
    assert m.competency("backend") is None      # < MIN_SAMPLES → no invented score
    assert m.samples("backend") == 2


def test_competency_is_evidence_based():
    m = EmployeeMemory("e1")
    for _ in range(4):
        m.record("task_done", "backend", ok=True)
    m.record("task_blocked", "backend", ok=False)
    # 4 ok, 1 fail over 5 → 0.8
    assert m.competency("backend") == 0.8
    m.record("task_done", "backend", ok=True, rolled_back=True)  # rollback penalizes
    assert m.competency("backend") < 0.8


def test_lessons_only_on_signal():
    m = EmployeeMemory("e1")
    m.record("task_done", "writing", ok=True)          # routine success → no lesson
    assert not m.lessons
    m.record("task_blocked", "writing", ok=False, ref="t9")  # failure → a lesson
    assert m.lessons and m.lessons[0].task_class == "writing"


def test_recall_top_k_by_confidence():
    m = EmployeeMemory("e1")
    m.add_lesson(Lesson("low", 1, "x", confidence=0.2))
    m.add_lesson(Lesson("high", 2, "x", confidence=0.9))
    assert m.recall("x", k=1)[0].text == "high"
    assert m.recall("other") == []


def test_memory_is_per_employee_isolated():
    a, b = EmployeeMemory("a"), EmployeeMemory("b")
    a.record("task_done", "backend", ok=True)
    assert a.samples("backend") == 1 and b.samples("backend") == 0


def test_runtime_records_outcomes_into_memory():
    t = Team()
    t.hire(Employee("eng", "backend engineer"))
    rt = OrgRuntime(t)
    for _ in range(3):
        rt.assign(Task("build", dri="eng", task_class="backend"))
    assert rt.memory_of("eng").samples("backend") == 3
    assert rt.memory_of("eng").competency("backend") == 1.0   # 3 successes


def test_runtime_records_blocked_as_evidence():
    t = Team()
    t.hire(Employee("eng", "backend engineer"))
    def boom(emp, task):
        raise RuntimeError("x")
    rt = OrgRuntime(t, executor=boom)
    for _ in range(3):
        rt.assign(Task("hard", dri="eng", task_class="backend"))
    mem = rt.memory_of("eng")
    assert mem.competency("backend") == 0.0 and len(mem.lessons) == 3   # failures learned
