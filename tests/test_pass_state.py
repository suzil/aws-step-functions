import contextlib
from contextlib import redirect_stdout
from io import StringIO

import pytest

from awsstepfuncs import PassState, StateMachine


def test_pass_state(compile_state_machine):
    pass_state1 = PassState("Pass 1", comment="The starting state")
    pass_state2 = PassState("Pass 2")
    pass_state3 = PassState("Pass 3")

    # Define the state machine
    pass_state1 >> pass_state2 >> pass_state3
    state_machine = StateMachine(start_state=pass_state1)

    # Make sure that the DAG is correctly specified
    assert [state.name for state in state_machine.start_state] == [
        pass_state1.name,
        pass_state2.name,
        pass_state3.name,
    ]

    # Check the output from compiling
    compiled = compile_state_machine(state_machine)
    assert compiled == {
        "StartAt": pass_state1.name,
        "States": {
            pass_state1.name: {
                "Comment": pass_state1.comment,
                "Type": "Pass",
                "Next": pass_state2.name,
            },
            pass_state2.name: {
                "Type": "Pass",
                "Next": pass_state3.name,
            },
            pass_state3.name: {
                "Type": "Pass",
                "End": True,
            },
        },
    }

    # Simulate the state machine
    with contextlib.closing(StringIO()) as fp:
        with redirect_stdout(fp):
            state_output = state_machine.simulate()
        stdout = fp.getvalue()

    assert state_output == {}
    assert (
        stdout
        == """Running Pass 1
Passing
Running Pass 2
Passing
Running Pass 3
Passing
"""
    )


def test_input_path(compile_state_machine):
    input_path = "$.dataset2"
    pass_state = PassState("Pass 1", input_path=input_path)

    # Define the state machine
    state_machine = StateMachine(start_state=pass_state)

    # Check the output from compiling
    compiled = compile_state_machine(state_machine)
    assert compiled == {
        "StartAt": pass_state.name,
        "States": {
            pass_state.name: {
                "InputPath": input_path,
                "Type": "Pass",
                "End": True,
            },
        },
    }

    # Simulate the state machine
    state_input = {
        "comment": "Example for InputPath.",
        "dataset1": {"val1": 1, "val2": 2, "val3": 3},
        "dataset2": {"val1": "a", "val2": "b", "val3": "c"},
    }
    state_output = state_machine.simulate(state_input=state_input)
    assert state_output == state_input["dataset2"]


def test_state_has_invalid_input_path():
    invalid_input_path = "$.dataset*"
    with pytest.raises(ValueError, match='Unsupported JSONPath operator: "*"'):
        PassState("Pass 1", input_path=invalid_input_path)