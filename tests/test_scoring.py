from cs263_agent_eval.eval.scoring import score_prediction
from cs263_agent_eval.schemas import BenchmarkTask, EvalCriteria


def test_score_prediction_exact_and_numeric_tolerance():
    task = BenchmarkTask(
        task_id="unit_001",
        task_family="document_workflow",
        instruction="Return values.",
        allowed_tools=[],
        gold_output={"name": "Ada", "score": 9.95},
        evaluation_criteria=EvalCriteria(
            exact_fields=["name", "score"],
            numeric_tolerances={"score": 0.1},
        ),
    )

    score = score_prediction(task, {"name": "Ada", "score": 10.0})

    assert score.field_accuracy == 1.0
    assert score.score_percent == 100.0
    assert score.task_success == 1.0


def test_score_prediction_set_fields_ignore_order():
    task = BenchmarkTask(
        task_id="unit_002",
        task_family="multi_app_workflow",
        instruction="Return values.",
        allowed_tools=[],
        gold_output={"items": ["a", "b"]},
        evaluation_criteria=EvalCriteria(set_fields=["items"]),
    )

    score = score_prediction(task, {"items": ["b", "a"]})

    assert score.field_accuracy == 1.0
    assert score.score_percent == 100.0
    assert score.task_success == 1.0


def test_score_prediction_set_fields_with_aliases_and_extra_penalty():
    task = BenchmarkTask(
        task_id="unit_003",
        task_family="multi_app_workflow",
        instruction="Return values.",
        allowed_tools=[],
        gold_output={"items": ["commute", "wifi"]},
        evaluation_criteria=EvalCriteria(
            set_fields=["items"],
            set_aliases={
                "items": {
                    "commute": ["normal_commuting"],
                    "wifi": ["premium_wifi"],
                }
            },
        ),
    )

    score = score_prediction(
        task,
        {"items": ["normal_commuting", "premium_wifi", "unrelated"]},
    )

    assert score.details["correct_checks"] == 2
    assert score.details["total_checks"] == 3
    assert score.score_percent == 66.67
    assert score.task_success == 0.0
