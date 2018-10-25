# Copyright 2018 The Cirq Developers
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Tuple, Union, List, Optional, cast, TypeVar, NamedTuple

import abc

import numpy as np

from cirq import value, protocols
from cirq.ops import raw_types
from cirq.type_workarounds import NotImplementedType


TSelf = TypeVar('TSelf', bound='EigenGate')


EigenComponent = NamedTuple(
    'EigenComponent',
    [
        # The θ in λ = exp(i π θ) where λ is a unique eigenvalue. The exponent
        # factor is used, instead of just a raw unit complex number, because it
        # disambiguates several cases. For example, when λ=-1 you can set θ to
        # -1 instead of +1 resulting in square root operations returning -i
        # instead of +1.
        ('eigenvalue_exponent_factor', float),

        # The projection matrix onto the eigenspace of the eigenvalue. Must
        # equal Σ_k |λ_k⟩⟨λ_k| where the |λ_k⟩ vectors form an orthonormal
        # basis for the eigenspace.
        ('eigenspace_projector', np.ndarray),
    ]
)


class EigenGate(raw_types.Gate):
    """A gate with a known eigendecomposition.

    EigenGate is particularly useful when one wishes for different parts of
    the same eigenspace to be extrapolated differently. For example, if a gate
    has a 2-dimensional eigenspace with eigenvalue -1, but one wishes for the
    square root of the gate to split this eigenspace into a part with
    eigenvalue i and a part with eigenvalue -i, then EigenGate allows this
    functionality to be unambiguously specified via the _eigen_components
    method.
    """

    def __init__(self, *,  # Forces keyword args.
                 exponent: Union[value.Symbol, float] = 1.0,
                 global_negate_rate: float = 0.0) -> None:
        """Initializes the parameters used to compute the gate's matrix.

        The eigenvalue of an eigenspace of the gate is computed by:
        1. Starting with an angle returned by the _eigen_components method.
            θ
        2. Shifting the angle by the global_negate_rate.
            θ + s
        3. Scaling the angle by the exponent.
            (θ + s) * e
        4. Converting from half turns to a complex number on the unit circle.
            exp(i * pi * (θ + s) * e)

        Args:
            exponent: How much to scale the eigencomponents' angles by when
                computing the gate's matrix.
            global_negate_rate: Determines how the global phase of the gate
                varies as the exponent varies. Specifically, the global phase
                factor will be exp(i * pi * global_negate_rate * exponent).
                In practice, this boils down to the eigencomponents' angles
                being shifted by `global_negate_rate` before being multiplied by
                `exponent`.

                For example, `cirq.X**t` uses a `global_negate_rate` of 0 but
                `cirq.Rx(t)` uses a `global_negate_rate` of -0.5, which is why
                `cirq.unitary(cirq.Rx(pi))` equals -iX instead of X.
        """
        self._exponent = exponent
        self._global_negate_rate = global_negate_rate
        self._canonical_exponent_cached = None

    # virtual method
    def _with_exponent(self: TSelf,
                       exponent: Union[value.Symbol, float]) -> TSelf:
        """Return the same kind of gate, but with a different exponent.

        Child classes should override this method if they have an __init__
        method with a differing signature.
        """
        return type(self)(
            exponent=exponent,
            global_negate_rate=self._global_negate_rate)

    @abc.abstractmethod
    def _eigen_components(self) -> List[Union[EigenComponent,
                                              Tuple[float, np.ndarray]]]:
        """Describes the eigendecomposition of the gate's matrix.

        Returns:
            A list of EigenComponent tuples. Each tuple in the list
            corresponds to one of the eigenspaces of the gate's matrix. Each
            tuple has two elements. The first element of a tuple is the θ in
            λ = exp(i π θ) (where λ is the eigenvalue of the eigenspace). The
            second element is a projection matrix onto the eigenspace.

        Examples:
            The Pauli Z gate's eigencomponents are:

                [
                    (0, np.array([[1, 0],
                                  [0, 0]])),
                    (1, np.array([[0, 0],
                                  [0, 1]])),
                ]

            Valid eigencomponents for Rz(π) = -iZ are:

                [
                    (-0.5, np.array([[1, 0],
                                    [0, 0]])),
                    (+0.5, np.array([[0, 0],
                                     [0, 1]])),
                ]

            But in principle you could also use this:

                [
                    (+1.5, np.array([[1, 0],
                                    [0, 0]])),
                    (-0.5, np.array([[0, 0],
                                     [0, 1]])),
                ]

                The choice between -0.5 and +1.5 does not affect the gate's
                matrix, but it does affect the matrix of powers of the gates
                (because (x+2)*s != x*s (mod 2) when s is a real number).

            The Pauli X gate's eigencomponents are:

                [
                    (0, np.array([[0.5, 0.5],
                                  [0.5, 0.5]])),
                    (1, np.array([[+0.5, -0.5],
                                  [-0.5, +0.5]])),
                ]
        """
        pass

    def _period(self) -> Optional[float]:
        """Determines how the exponent parameter is canonicalized when equating.

        Returns:
            None if the exponent should not be canonicalized. Otherwise a float
            indicating the period of the exponent. If the period is p, then a
            given exponent will be shifted by p until it is in the range
            (-p/2, p/2] during initialization.
        """
        exponents = [e + self._global_negate_rate
                     for e, _ in self._eigen_components()]
        real_periods = [abs(2/e) for e in exponents if e != 0]
        if not real_periods:
            return 0
        int_periods = [int(np.round(e)) for e in real_periods]
        if any(i != r for i, r in zip(real_periods, int_periods)):
            return None
        return np.lcm.reduce(int_periods)

    def __pow__(self: TSelf, exponent: Union[float, value.Symbol]) -> TSelf:
        new_exponent = protocols.mul(self._exponent, exponent, NotImplemented)
        if new_exponent is NotImplemented:
            return NotImplemented
        return self._with_exponent(exponent=new_exponent)

    @property
    def _canonical_exponent(self):
        if self._canonical_exponent_cached is None:
            period = self._period()
            if not period or isinstance(self._exponent, value.Symbol):
                self._canonical_exponent_cached = self._exponent
            else:
                self._canonical_exponent_cached = self._exponent % period
        return self._canonical_exponent_cached

    def _identity_tuple(self):
        return (type(self),
                self._canonical_exponent,
                self._global_negate_rate)

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self._identity_tuple() == other._identity_tuple()

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self._identity_tuple())

    def _trace_distance_bound_(self):
        if isinstance(self._exponent, value.Symbol):
            return 1

        angles = [half_turns for half_turns, _ in self._eigen_components()]
        min_angle = min(angles)
        max_angle = max(angles)
        return abs((max_angle - min_angle) * self._exponent * 3.5)

    def _has_unitary_(self) -> bool:
        return not self._is_parameterized_()

    def _unitary_(self) -> Union[np.ndarray, NotImplementedType]:
        if self._is_parameterized_():
            return NotImplemented
        e = cast(float, self._exponent)
        return np.sum([
            component * 1j**(
                    2 * e * (half_turns + self._global_negate_rate))
            for half_turns, component in self._eigen_components()
        ], axis=0)

    def _is_parameterized_(self) -> bool:
        return isinstance(self._exponent, value.Symbol)

    def _resolve_parameters_(self: TSelf, param_resolver) -> TSelf:
        return self._with_exponent(
                exponent=param_resolver.value_of(self._exponent))
