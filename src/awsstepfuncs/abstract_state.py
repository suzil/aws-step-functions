"""Abstract state definitions.

Based on this table: https://states-language.net/spec.html#state-type-table
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from awsstepfuncs.error_handlers import Catcher, Retrier
from awsstepfuncs.errors import AWSStepFuncsValueError
from awsstepfuncs.printer import Printer, Style
from awsstepfuncs.reference_path import ReferencePath
from awsstepfuncs.types import ResourceToMockFn

MAX_STATE_NAME_LENGTH = 128


class AbstractState(ABC):
    """An Amazon States Language state including Name, Comment, and Type."""

    def __init__(self, name: str, comment: Optional[str] = None):
        """Initialize subclasses.

        Args:
            name: The name of the state. Must be unique within the state machine
                and its length cannot exceed 128 characters.
            comment: A human-readable description of the state.

        Raises:
            AWSStepFuncsValueError: Raised when the state name exceeds 128 characters.
        """
        if len(name) > MAX_STATE_NAME_LENGTH:
            raise AWSStepFuncsValueError(
                f"State name cannot exceed {MAX_STATE_NAME_LENGTH} characters"
            )

        self.name = name
        self.comment = comment
        self.next_state: Optional[AbstractState] = None
        self.print: Printer  # Used for simulations

    def compile(self) -> Dict[str, Any]:  # noqa: A003
        """Compile the state to Amazon States Language.

        Returns:
            A dictionary representing the compiled state in Amazon States
            Language.
        """
        assert self.state_type  # type: ignore
        compiled = {"Type": self.state_type}  # type: ignore
        if comment := self.comment:
            compiled["Comment"] = comment
        return compiled

    @abstractmethod
    def _execute(self, state_input: Any, resource_to_mock_fn: ResourceToMockFn) -> Any:
        """Execute the state.

        Args:
            state_input: The input state data.
            resource_to_mock_fn: A mapping of resource URIs to mock functions to
                use if the state performs a task.

        Raises:
            NotImplementedError: Raised when child classes do not implement this
                method.
        """
        raise NotImplementedError

    def simulate(
        self, state_input: Any, *, resource_to_mock_fn: ResourceToMockFn
    ) -> Any:
        """Simulate the state including input and output processing.

        Args:
            state_input: The input to the state.
            resource_to_mock_fn: A mapping of resource URIs to mock functions to
                use if the state performs a task.

        Returns:
            The output of the state after applying any output processing.
        """
        return self._execute(state_input, resource_to_mock_fn) or {}

    def __rshift__(self, other: AbstractState, /) -> AbstractState:
        """Overload >> operator to set state execution order.

        Args:
            other: The other state besides self.

        Returns:
            The latest state (for right shift, the right state).
        """
        self.next_state = other
        return other

    def __iter__(self) -> AbstractState:
        """Iterate through the states."""
        self._current: Optional[AbstractState] = self
        return self._current

    def __next__(self) -> AbstractState:
        """Get the next state."""
        current = self._current
        if not current:
            raise StopIteration

        self._current = current.next_state
        return current

    def __repr__(self) -> str:
        """Create a string representation of a state.

        Returns:
            String representation of a state.
        """
        state_repr = f"{self.__class__.__name__}(name={self.name!r}"
        if self.comment:
            state_repr += f", comment={self.comment!r}"
        if self.next_state:
            state_repr += f", next_state={self.next_state.name!r}"
        state_repr += ")"
        return state_repr

    def __str__(self) -> str:
        """Create a human-readable string representation of a state.

        Returns:
            Human-readable string representation of a state.
        """
        return f"{self.__class__.__name__}({self.name!r})"


class AbstractInputPathOutputPathState(AbstractState):
    """An Amazon States Language state including InputPath and OutputPath.

    `input_path` and `output_path` let you control what is input and output from
    a state by using Reference Paths.
    """

    def __init__(
        self, *args: Any, input_path: str = "$", output_path: str = "$", **kwargs: Any
    ):
        """Initialize subclasses.

        Args:
            args: Args to pass to parent classes.
            input_path: Used to select a portion of the state input. Default is
                $ (pass everything).
            output_path: Used to select a portion of the state output. Default
                is $ (pass everything).
            kwargs: Kwargs to pass to parent classes.
        """
        super().__init__(*args, **kwargs)
        self.input_path = ReferencePath(input_path)
        self.output_path = ReferencePath(output_path)

    def simulate(self, state_input: Any, resource_to_mock_fn: ResourceToMockFn) -> Any:
        """Simulate the state including input and output processing.

        Args:
            state_input: The input to the state.
            resource_to_mock_fn: A mapping of resource URIs to mock functions to
                use if the state performs a task.

        Returns:
            The output of the state after applying any output processing.
        """
        state_input = self._apply_input_path(state_input)
        state_output = self._execute(state_input, resource_to_mock_fn) or {}
        return self._apply_output_path(state_output)

    def _apply_input_path(self, state_input: Any) -> Any:
        """Apply input path to some state input."""
        state_input = self.input_path.apply(state_input)
        self.print(
            f"State input after applying input path of {self.input_path}:",
            state_input,
            style=Style.DIM,
        )
        return state_input

    def _apply_output_path(self, state_output: Any) -> Any:
        """Apply output path to some state output."""
        state_output = self.output_path.apply(state_output)
        self.print(
            f"State output after applying output path of {self.output_path}:",
            state_output,
            style=Style.DIM,
        )
        return state_output

    def compile(self) -> Dict[str, Any]:  # noqa: A003
        """Compile the state to Amazon States Language.

        Returns:
            A dictionary representing the compiled state in Amazon States
            Language.
        """
        compiled = super().compile()
        if input_path := self.input_path:
            compiled["InputPath"] = str(input_path)
        if output_path := self.output_path:
            compiled["OutputPath"] = str(output_path)
        return compiled


class AbstractNextOrEndState(AbstractInputPathOutputPathState):
    """An Amazon States Language state including Next or End."""

    def compile(self) -> Dict[str, Any]:  # noqa: A003
        """Compile the state to Amazon States Language.

        Returns:
            A dictionary representing the compiled state in Amazon States
            Language.
        """
        compiled = super().compile()
        if next_state := self.next_state:
            compiled["Next"] = next_state.name
        else:
            compiled["End"] = True
        return compiled


class AbstractResultPathState(AbstractNextOrEndState):
    """An Amazon States Language state including ResultPath."""

    def __init__(self, *args: Any, result_path: Optional[str] = "$", **kwargs: Any):
        """Initialize subclasses.

        Args:
            args: Args to pass to parent classes.
            result_path: Specifies where (in the input) to place the "output" of
                the virtual task specified in Result. The input is further filtered
                as specified by the OutputPath field (if present) before being used
                as the state's output. Default is $ (pass only the output state).
            kwargs: Kwargs to pass to parent classes.
        """
        super().__init__(*args, **kwargs)
        self.result_path = ReferencePath(result_path) if result_path else None

    def compile(self) -> Dict[str, Any]:  # noqa: A003
        """Compile the state to Amazon States Language.

        Returns:
            A dictionary representing the compiled state in Amazon States
            Language.
        """
        compiled = super().compile()
        if self.result_path is None or self.result_path:
            compiled["ResultPath"] = str(self.result_path) if self.result_path else None
        return compiled

    def simulate(self, state_input: Any, resource_to_mock_fn: ResourceToMockFn) -> Any:
        """Simulate the state including input and output processing.

        Args:
            state_input: The input to the state.
            resource_to_mock_fn: A mapping of resource URIs to mock functions to
                use if the state performs a task.

        Returns:
            The output of the state after applying any output processing.
        """
        state_input = self._apply_input_path(state_input)
        state_output = self._execute(state_input, resource_to_mock_fn) or {}
        state_output = self._apply_result_path(state_input, state_output)
        return self._apply_output_path(state_output)

    def _apply_result_path(self, state_input: Any, state_output: Any) -> Any:
        """Apply ResultPath to combine state input with state output.

        Args:
            state_input: The input state.
            state_output: The output state.

        Returns:
            The state resulting from applying ResultPath.
        """
        if str(self.result_path) == "$":
            # Just keep state output
            output = state_output

        elif self.result_path is None:
            # Just keep state input, discard state_output
            output = state_input

        elif match := re.fullmatch(r"\$\.([A-Za-z]+)", str(self.result_path)):
            # Move the state output as a key in state input
            result_key = match.group(1)
            state_input[result_key] = state_output
            output = state_input

        else:  # pragma: no cover
            assert False, "Should never happen"  # noqa: PT015

        self.print(
            f"Output from applying result path of {self.result_path}:",
            output,
            style=Style.DIM,
        )
        return output


class AbstractParametersState(AbstractResultPathState):
    """An Amazon States Language state including Parameters."""

    def __init__(
        self, *args: Any, parameters: Optional[Dict[str, Any]] = None, **kwargs: Any
    ):
        """Initialize subclasses.

        Args:
            args: Args to pass to parent classes.
            parameters: Use the Parameters field to create a collection of
                key-value pairs that are passed as input. The values of each can
                either be static values that you include in your state machine
                definition, or selected from either the input or the context object
                with a path. For key-value pairs where the value is selected using a
                path, the key name must end in .$.
            kwargs: Kwargs to pass to parent classes.
        """
        super().__init__(*args, **kwargs)
        self.parameters = parameters or {}

    def compile(self) -> Dict[str, Any]:  # noqa: A003
        """Compile the state to Amazon States Language.

        Returns:
            A dictionary representing the compiled state in Amazon States
            Language.
        """
        compiled = super().compile()
        if parameters := self.parameters:
            compiled["Parameters"] = parameters
        return compiled


class AbstractResultSelectorState(AbstractParametersState):
    """An Amazon States Language state including ResultSelector."""

    def __init__(
        self, *args: Any, result_selector: Dict[str, str] = None, **kwargs: Any
    ):
        """Initialize subclasses.

        Args:
            args: Args to pass to parent classes.
            result_selector: Used to manipulate a state's result before
                ResultPath is applied.
            kwargs: Kwargs to pass to parent classes.

        Raises:
            AWSStepFuncsValueError: Raised when the result selector is invalid.
        """
        super().__init__(*args, **kwargs)
        if result_selector:
            try:
                self._validate_result_selector(result_selector)
            except AWSStepFuncsValueError:
                raise

        self.result_selector = result_selector

    @staticmethod
    def _validate_result_selector(result_selector: Dict[str, str]) -> None:
        """Validate result selector.

        Args:
            result_selector: The result selector to validate.

        Raises:
            AWSStepFuncsValueError: Raised when a key doesn't end with ".$".
            AWSStepFuncsValueError: Raised when a ReferencePath is invalid.
        """
        for key, reference_path in result_selector.items():
            if not key[-2:] == ".$":
                raise AWSStepFuncsValueError(
                    "All resource selector keys must end with .$"
                )

            # TODO: Check if ReferencePath(...) is being called twice
            ReferencePath(reference_path)

    def compile(self) -> Dict[str, Any]:  # noqa: A003
        """Compile the state to Amazon States Language.

        Returns:
            A dictionary representing the compiled state in Amazon States
            Language.
        """
        compiled = super().compile()
        if result_selector := self.result_selector:
            compiled["ResultSelector"] = result_selector
        return compiled

    def simulate(self, state_input: Any, resource_to_mock_fn: ResourceToMockFn) -> Any:
        """Simulate the state including input and output processing.

        Args:
            state_input: The input to the state.
            resource_to_mock_fn: A mapping of resource URIs to mock functions to
                use if the state performs a task.

        Returns:
            The output of the state after applying any output processing.
        """
        state_input = self._apply_input_path(state_input)
        state_output = self._execute(state_input, resource_to_mock_fn) or {}
        if self.result_selector:
            state_output = self._apply_result_selector(state_output)
            self.print(
                f"State output after applying result selector {self.result_selector}:",
                state_output,
                style=Style.DIM,
            )
        state_output = self._apply_result_path(state_input, state_output)
        return self._apply_output_path(state_output)

    def _apply_result_selector(self, state_output: Any) -> Dict[str, Any]:
        """Apply the ResultSelector to select a portion of the state output.

        Args:
            state_output: The state output to filter.

        Returns:
            The filtered state output.
        """
        new_state_output = {}
        for key, reference_path in self.result_selector.items():  # type: ignore
            key = key[:-2]  # Strip ".$"
            if extracted := ReferencePath(reference_path).apply(state_output):
                new_state_output[key] = extracted

        return new_state_output


class AbstractRetryCatchState(AbstractResultSelectorState):
    """An Amazon States Language state including Retry and Catch."""

    def __init__(self, *args: Any, **kwargs: Any):
        """Initialize subclasses.

        Args:
            args: Args to pass to parent classes.
            kwargs: Kwargs to pass to parent classes.
        """
        super().__init__(*args, **kwargs)
        self.retriers: List[Retrier] = []
        self.catchers: List[Catcher] = []

    def compile(self) -> Dict[str, Any]:  # noqa: A003
        """Compile the state to Amazon States Language.

        Returns:
            A dictionary representing the compiled state in Amazon States
            Language.
        """
        compiled = super().compile()
        if retriers := self.retriers:
            compiled["Retry"] = [retrier.compile() for retrier in retriers]
        if catchers := self.catchers:
            compiled["Catch"] = [catcher.compile() for catcher in catchers]
        return compiled

    def add_retrier(
        self,
        error_equals: List[str],
        *,
        interval_seconds: Optional[int] = None,
        backoff_rate: Optional[float] = None,
        max_attempts: Optional[int] = None,
    ) -> AbstractRetryCatchState:
        """Add a Retrier to the state.

        Retry the state by specifying a list of Retriers that describes the
        retry policy for different errors.

        Args:
            error_equals: A list of error names.
            interval_seconds: The number of seconds before the first retry
                attempt. Defaults to 1 if not specified.
            backoff_rate: A number which is the multiplier that increases the
                retry interval on each attempt. Defaults to 2.0 if not specified.
            max_attempts: The maximum number of retry to attempt. Defaults to 3
                if not specified. A value of zero means that the error should never
                be retried.

        Returns:
            Itself to allow for chaining.
        """
        retrier = Retrier(
            error_equals=error_equals,
            interval_seconds=interval_seconds,
            backoff_rate=backoff_rate,
            max_attempts=max_attempts,
        )
        self.retriers.append(retrier)
        return self

    def add_catcher(
        self,
        error_equals: List[str],
        *,
        next_state: AbstractState,
    ) -> AbstractRetryCatchState:
        """Add a Catcher to the state.

        When a state reports an error and either there is no Retrier, or retries
        have failed to resolve the error, the interpreter will try to find a
        relevant Catcher which determines which state to transition to.

        `"States.ALL"` is the catch-all error message; that is, any error will
        be caught with `"States.ALL"`. Right now it's the only error code
        supported when simulating.

        If no catcher can be applied, then the state machine will terminate.

        Args:
            error_equals: A list of error names.
            next_state: The name of the next state.

        Returns:
            Itself to allow for chaining.
        """
        catcher = Catcher(
            error_equals=error_equals,
            next_state=next_state,
        )
        self.catchers.append(catcher)
        return self
