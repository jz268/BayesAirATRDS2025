"""Define types for airports in the network."""
from dataclasses import dataclass, field
from typing import Optional

import pyro
import pyro.distributions as dist
import pyro.distributions
import torch

from bayes_air.types.flight import Flight
from bayes_air.types.util import AirportCode, Time


@dataclass
class QueueEntry:
    """An entry in a runway queue.

    Attributes:
        flight: The flight associated with this queue entry.
        queue_start_time: The time at which the flight entered the queue.
        total_wait_time: The total duration the flight has spent in the queue.
        assigned_service_time: The time at which the flight will be serviced.
    """

    flight: Flight
    queue_start_time: Time
    total_wait_time: Time = field(default_factory=lambda: Time(0.0))
    assigned_service_time: Optional[Time] = None

@dataclass
class DepartureQueueEntry:
    flight: Flight
    ready_time: Time
    approved_time: Optional[Time] = None


@dataclass
class Airport:
    """Represents a single airport in the network.

    Attributes:
        code: The airport code.
        mean_service_time: The mean service time for departing and arriving aircraft
        runway_use_time_std_dev: The standard deviation of the runway use time for
            departing and arriving aircraft.
        mean_turnaround_time: The nominal turnaround time for aircraft landing at
            this airport.
        turnaround_time_std_dev: The standard deviation of the turnaround time for
            aircraft landing at this airport.
        runway_queue: The queue of aircraft waiting to take off or land.
        turnaround_queue: The queue of aircraft waiting to be cleaned/refueled/etc..
            Each entry in this queue represents a time at which the aircraft will be
            ready for its next departure.
        available_aircraft: a list of times at which aircraft became available (after
            turnaround).
        last_departure_time: The time at which the last aircraft departed.
    """

    code: AirportCode
    mean_service_time: Time = field(default_factory=lambda: Time(1.0))
    runway_use_time_std_dev: Time = field(default_factory=lambda: Time(1.0))
    mean_turnaround_time: Time = field(default_factory=lambda: Time(1.0))
    turnaround_time_std_dev: Time = field(default_factory=lambda: Time(1.0))
    num_available_aircraft: torch.tensor = field(
        default_factory=lambda: torch.tensor(0.0)
    )
    base_cancel_prob: torch.tensor = field(default_factory=lambda: torch.tensor(0.0))
    runway_queue: list[QueueEntry] = field(default_factory=list)
    turnaround_queue: list[Time] = field(default_factory=list)
    available_aircraft: list[Time] = field(default_factory=list)
    last_departure_time: Time = field(default_factory=lambda: Time(0.0))

    obs_none: bool = field(default_factory=lambda: False)

    # the default is to not give any priority to landing flights
    use_max_holding_time: bool = field(default_factory = lambda: False)
    soft_max_holding_time: Time = field(default_factory=lambda: Time(0.0))
    max_holding_time: Time = field(default_factory=lambda: Time(0.0))

    use_max_waiting_time: bool = field(default_factory=lambda: False)
    max_waiting_time: Time = field(default_factory=lambda: Time(0.0))

    def update_available_aircraft(self, time: Time) -> None:
        """Update the number of available aircraft by checking the turnaround queue.

        Args:
            time: The current time.
        """
        new_turnaround_queue = []
        for turnaround_time in self.turnaround_queue:
            if turnaround_time <= time:
                # The aircraft is ready to depart, so add it to the available aircraft
                self.available_aircraft.append(turnaround_time)
                self.num_available_aircraft = self.num_available_aircraft + 1
            else:
                # The aircraft is not yet ready to depart, so add it to the new
                # turnaround queue
                new_turnaround_queue.append(turnaround_time)

        # Update the turnaround queue
        self.turnaround_queue = new_turnaround_queue

    def update_runway_queue(
        self, time: Time, var_prefix: str = "",
    ) -> tuple[list[Flight], list[Flight]]:
        """Update the runway queue by removing flights that have been serviced.

        Args:
            time: The current time.
            var_prefix: the prefix for sampled variable names

        Returns: a list of flights that have departed and a list of flights that have
            landed.
        """
        # While the flight at the front of the queue is ready to be serviced, service it
        departed_flights = []
        landed_flights = []
        cancelled_flights = []
        diverted_flights = []

        # if this is too slow then remove it i guess
        # self.runway_queue.sort(key=lambda x: x.queue_start_time)

        # # landing flights that have been waiting for too long
        # # based on elapsed time since entering queue
        # if self.use_max_holding_time:
        #     priority_runway_queue = []
        #     regular_runway_queue = []
        #     for qe in self.runway_queue:
        #         no_service_time_assigned = qe.assigned_service_time is None
        #         cannot_wait_longer = (time - qe.queue_start_time) > self.soft_max_holding_time
        #         if no_service_time_assigned and cannot_wait_longer:
        #             priority_runway_queue.append(qe)
        #         else:
        #             regular_runway_queue.append(qe)
        #     self.runway_queue = priority_runway_queue + regular_runway_queue

        # # print([round(qe.queue_start_time.item(),2) for qe in self.runway_queue])

        # # process flights to be cancelled or diverted
        # fresh_runway_queue = []
        # for queue_entry in self.runway_queue:
        #     flight = queue_entry.flight
        #     arriving = queue_entry.flight.destination == self.code
        #     departing = not arriving # TODO: should waiting apply to all?

        #     if self.use_max_holding_time and arriving \
        #         and queue_entry.total_wait_time > self.max_holding_time:
        #         self._assign_diversion(queue_entry, var_prefix)
        #         diverted_flights.append(flight)

        #     elif self.use_max_waiting_time and departing \
        #         and queue_entry.total_wait_time > self.max_waiting_time:
        #         self._assign_cancellation(queue_entry, var_prefix)
        #         cancelled_flights.append(flight)

        #     else:
        #         fresh_runway_queue.append(queue_entry)

        # self.runway_queue = fresh_runway_queue
            
        while self.runway_queue and (
            self.runway_queue[0].assigned_service_time is None
            or self.runway_queue[0].assigned_service_time <= time
        ):
            # If no service time is assigned, assign one now by sampling from
            # the service time distribution
            if self.runway_queue[0].assigned_service_time is None:
                self._assign_service_time(self.runway_queue[0], time, var_prefix)

            # If the service time has elapsed, it takes off or lands
            if self.runway_queue[0].assigned_service_time <= time:
                queue_entry = self.runway_queue.pop(0)
                flight = queue_entry.flight

                departing = flight.origin == self.code
                if departing:
                    # Takeoff! Assign a departure time and add the flight to the
                    # list of departed flights
                    self._assign_departure_time(queue_entry, var_prefix)
                    departed_flights.append(flight)
                else:
                    # Landing! Assign an arrival time and add the aircraft to the
                    # turnaround queue
                    self._assign_arrival_time(queue_entry, var_prefix)
                    self._assign_turnaround_time(flight, var_prefix)
                    landed_flights.append(flight)

                # # TODO: for >1 airport case we need to handle this more carefully...
                # self._assign_success(queue_entry, var_prefix)

        return departed_flights, landed_flights, cancelled_flights, diverted_flights

    # def _deterministic_time(self, flight, var_prefix, suffix, value, device):
    #     return pyro.deterministic(
    #         var_prefix + str(flight) + suffix,
    #         Time(value).to(device)
    #     )
    
    # def _deterministic_tensor(self, flight, var_prefix, suffix, value, device):
    #     return pyro.deterministic(
    #         var_prefix + str(flight) + suffix,
    #         torch.tensor(value).to(device)
    #     )
    
    # def _sample_time(self, flight, var_prefix, suffix, value, device, std=None, obs=None):
    #     if std is None:
    #         return pyro.sample(
    #             var_prefix + str(flight) + suffix,
    #             dist.Delta(Time(value).to(device))
    #         )
    #     else:
    #         return pyro.sample(
    #             var_prefix + str(flight) + suffix,
    #             dist.Normal(
    #                 Time(value).to(device), 
    #                 Time(std).to(device) # arbitrary, shouldn't matter
    #             ),
    #             obs=obs
    #         )
    
    # def _sample_tensor(self, flight, var_prefix, suffix, value, device, std=None, obs=None):
    #     if std is None:
    #         return pyro.deterministic(
    #             var_prefix + str(flight) + suffix,
    #             dist.Delta(torch.tensor(value).to(device))
    #         )
    #     else:
    #         return pyro.sample(
    #             var_prefix + str(flight) + suffix,
    #             dist.Normal(
    #                 torch.tensor(value).to(device),
    #                 torch.tensor(std).to(device)
    #             ),
    #             obs=obs
    #         )
    
    # def _assign_success(
    #     self,
    #     queue_entry: QueueEntry,
    #     var_prefix: str = "",
    # ):
    #     flight = queue_entry.flight
    #     device = flight.scheduled_departure_time.device

    #     def zero_det_tensor(suffix):
    #         return self._deterministic_tensor(flight, var_prefix, suffix, 0.0, device)
        
    #     flight.simulated_failed = zero_det_tensor("_failed")
    
    # def _assign_cancellation(
    #     self,
    #     queue_entry: QueueEntry,
    #     var_prefix: str = "",
    # ):
    #     flight = queue_entry.flight
    #     device = flight.scheduled_departure_time.device

    #     def zero_det_time(suffix):
    #         return self._deterministic_time(flight, var_prefix, suffix, 0.0, device)
    #     def one_det_tensor(suffix):
    #         return self._deterministic_tensor(flight, var_prefix, suffix, 1.0, device)
    #     def zero_sample_time(suffix):
    #         return self._sample_time(flight, var_prefix, suffix, 0.0, device, std=1.0)

    #     if queue_entry.assigned_service_time is None:
    #         zero_sample_time("_departure_service_time")

    #     flight.simulated_departure_time = zero_det_time("_simulated_departure_time")

    #     # flight.simulated_cancelled = one_sample_tensor("_cancelled")
    #     # TODO: actually how do we handle this two possible sample site thing?
    #     flight.simulated_failed = one_det_tensor("_failed")

    #     # print(
    #     #     f"\t{queue_entry.flight} assigned cancellation (entered queue {queue_entry.queue_start_time} and waited {queue_entry.total_wait_time})"
    #     # )

    # def _assign_diversion(
    #     self,
    #     queue_entry: QueueEntry,
    #     var_prefix: str = ""
    # ):
    #     flight = queue_entry.flight
    #     device = flight.scheduled_arrival_time.device

    #     def zero_det_time(suffix):
    #         return self._deterministic_time(flight, var_prefix, suffix, 0.0, device)
    #     def one_det_tensor(suffix, obs=None):
    #         return self._deterministic_tensor(flight, var_prefix, suffix, 1.0, device)
    #     def zero_sample_time(suffix):
    #         return self._sample_time(flight, var_prefix, suffix, 0.0, device, std=1.0)

    #     if queue_entry.assigned_service_time is None:
    #         zero_sample_time("_arrival_service_time")

    #     zero_sample_time("_turnaround_time") # is this necessary?
    #     flight.simulated_arrival_time = zero_det_time("_simulated_arrival_time")

    #     # flight.simulated_diverted = one_sample_tensor("_diverted")
    #     flight.simulated_failed = one_det_tensor("_failed")

    #     # print(
    #     #     f"\t{queue_entry.flight} assigned diversion (entered queue {queue_entry.queue_start_time} and waited {queue_entry.total_wait_time})"
    #     # )
        

    def _assign_service_time(
        self, queue_entry: QueueEntry, time: Time, var_prefix: str = ""
    ) -> None:
        """Sample a random service time for an entry in the runway queue.

        Args:
            queue_entry: The queue entry to assign a service time to.
            time: The current time.
            var_prefix: prefix for sampled variable names.
        """
        departing = queue_entry.flight.origin == self.code
        var_name = var_prefix + str(queue_entry.flight)
        var_name += "_departure" if departing else "_arrival"
        var_name += "_service_time"

        # service_time = pyro.sample(
        #     var_name,
        #     dist.Exponential(
        #         1.0 / self.mean_service_time.reshape(-1)
        #     ),
        # ).squeeze() # TODO: why? some weird shape issue that randomly appears?
        # # is there like something we have to do here when sampling?
        service_time = dist.Exponential(
            1.0 / self.mean_service_time.reshape(-1)
        ).rsample().squeeze()

        # if service_time.size() != torch.Size([]):
        #     raise ValueError(service_time)

        # Update the waiting times for all aircraft
        for other_queue_entry in self.runway_queue:
            other_queue_entry.total_wait_time = (
                other_queue_entry.total_wait_time + service_time
            )

        # Update the time at which this aircraft leaves the queue
        queue_entry.assigned_service_time = (
            queue_entry.queue_start_time + queue_entry.total_wait_time
        )

        # print(
        #     f"\t{queue_entry.flight} assigned service time {queue_entry.assigned_service_time} (entered queue {queue_entry.queue_start_time} and sampled service time {service_time})"
        # )

    def _assign_departure_time(
        self,
        queue_entry: QueueEntry,
        var_prefix: str = "",
    ) -> None:
        """Sample a random departure time for a flight that is using the runway.

        Args:
            queue_entry: The queue entry for the flight to assign a departure time to.
            var_prefix: prefix for sampled variable names.
        """

        var_name = var_prefix + str(queue_entry.flight) + "_simulated_departure_time"
        obs = queue_entry.flight.actual_departure_time if not self.obs_none else None

        queue_entry.flight.simulated_departure_time = pyro.sample(
            var_name,
            dist.Normal(
                queue_entry.queue_start_time + queue_entry.total_wait_time,
                self.runway_use_time_std_dev,
            ),
            obs=obs,
        )

        # print(
        #     f"\t{queue_entry.flight} departing at {queue_entry.flight.simulated_departure_time} (entered queue {queue_entry.queue_start_time} and waited {queue_entry.total_wait_time})"
        # )

    def _assign_arrival_time(
        self, 
        queue_entry: QueueEntry, 
        var_prefix: str = "",
    ) -> None:
        """Sample a random arrival time for a flight that is using the runway.

        Args:
            queue_entry: The queue entry for the flight to assign a arrival time to.
            var_prefix: prefix for sampled variable names.
        """

        var_name = var_prefix + str(queue_entry.flight) + "_simulated_arrival_time"
        # obs = queue_entry.flight.actual_arrival_time if not self.obs_none else None
        obs = None

        # queue_entry.flight.simulated_arrival_time = pyro.sample(
        #     var_name,
        #     dist.Normal(
        #         queue_entry.queue_start_time + queue_entry.total_wait_time,
        #         self.runway_use_time_std_dev,
        #     ),
        #     obs=obs,
        # )
        queue_entry.flight.simulated_arrival_time = \
            dist.Normal(
                queue_entry.queue_start_time + queue_entry.total_wait_time,
                self.runway_use_time_std_dev,
            ).rsample()
                    
        # print(
        #     f"\t{queue_entry.flight} arriving at {queue_entry.flight.simulated_arrival_time} (entered queue {queue_entry.queue_start_time} and waited {queue_entry.total_wait_time})"
        # )

    def _assign_turnaround_time(self, flight: Flight, var_prefix: str = "") -> None:
        """Sample a random turnaround time for an arrived aircraft.

        Args:
            flight: The flight to assign a turnaround time to.
            var_prefix: prefix for sampled variable names.
        """
        # turnaround_time = pyro.sample(
        #     var_prefix + str(flight) + "_turnaround_time",
        #     dist.Normal(self.mean_turnaround_time, self.turnaround_time_std_dev),
        # )
        turnaround_time = dist.Normal(
            self.mean_turnaround_time, 
            self.turnaround_time_std_dev
        ).rsample().squeeze()
        # print(flight.simulated_arrival_time, turnaround_time)
        # exit()
        self.turnaround_queue.append(flight.simulated_arrival_time + turnaround_time)


@dataclass
class SourceSupernode:
    """
    Represents aggregation of all source airports for incoming flights,
    a simplified approximation used for single node analysis only
    For now, we just attempt to emit flight at ready time

    Attributes:
        departure_queue_by_destination: 
        last_departure_time: unused?
    """

    source_codes: list[AirportCode]
    dest_codes: list[AirportCode]
    departure_queues: dict[
        AirportCode, list[DepartureQueueEntry]
        ] = field(default_factory=dict)
    # departure queue is for each destination airport!
    last_departure_time: Time = field(default_factory=lambda: Time(0.0)) # unused?
    runway_use_time_std_dev: Time = field(default_factory=lambda: Time(1.0))

    obs_none: bool = field(default_factory=lambda: False)

    def __post_init__(self):
        # initialize departure queues
        for code in self.dest_codes:
            self.departure_queues[code] = []

    def update_departure_queue_for_destination(
        self, 
        time: Time, 
        destination_code: AirportCode,
        # remaining_arrival_capacity: dict[AirportCode, int],
        var_prefix: str = "",
    ) -> tuple[list[Flight], list[Flight]]:
        """Update the runway queue by removing flights that have been serviced.
        TODO: update this!!
        Args:
            time: The current time.
            var_prefix: the prefix for sampled variable names

        Returns: a list of flights that have departed
        """
        departed_flights = []
        departure_queue = self.departure_queues[destination_code]

        # for now we just pump them out as we get them
        while departure_queue and (
            departure_queue[0].ready_time <= time
        ):
            departure_queue_entry = departure_queue.pop(0)
            flight = departure_queue_entry.flight

            # Takeoff! Assign a departure time and add the flight to the
            # list of departed flights
            self._assign_departure_time(departure_queue_entry, var_prefix)

            if not flight.adjusted_cancelled:
                departed_flights.append(flight)

        self.departure_queues[destination_code] = departure_queue
        return departed_flights

    def _assign_departure_time(
        self,
        departure_queue_entry: DepartureQueueEntry,
        var_prefix: str = "",
    ) -> None:
        """Sample a random departure time for a flight that is using the runway.

        Args:
            queue_entry: The queue entry for the flight to assign a departure time to.
            var_prefix: prefix for sampled variable names.
        """
        # departure_queue_entry.flight.simulated_departure_time = pyro.sample(
        #     var_prefix + str(departure_queue_entry.flight) + "_simulated_departure_time",
        #     dist.Normal(
        #         departure_queue_entry.flight.adjusted_departure_time,
        #         self.runway_use_time_std_dev,
        #     ),
        # )

        departure_queue_entry.flight.simulated_departure_time = (
            departure_queue_entry.flight.adjusted_departure_time
        )

        # if departure_queue_entry.flight.flight_number == 'DL:2358' \
        #     and departure_queue_entry.flight.destination == 'LGA':
        #     print(crs_dep_time, carrier_delay, late_aircraft_delay)

        # print(
        #     f"\t{queue_entry.flight} departing at {queue_entry.flight.simulated_departure_time} (entered queue {queue_entry.queue_start_time} and waited {queue_entry.total_wait_time})"
        # )



@dataclass
class SinkSupernode:
    pass
