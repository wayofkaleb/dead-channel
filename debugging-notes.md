# Dead Channel case notes

The Emberlane desk looks quiet at midnight UTC on January 18, 2026. The replay freezes that clock so the same files always give you the same result.

The gateway's last usable event happened at 23:57:38 UTC, 142 seconds before the replay clock. It arrived just 10 seconds before midnight. A monitor that checks arrival time alone would call the gateway fresh.

The gateway collector checked in at 23:59:52 UTC, eight seconds before midnight. Two gateway rows arrived after that, and the parser rejected both. One had an invalid seconds value and the other had a timestamp with no time zone. The auth and match feeds both had usable events within the last 10 seconds. Together, these clues point to bad timestamps in the gateway feed while its collector was still checking in.

The replay shows where those two rows were dropped. To find where the timestamps went wrong, compare a raw record from the gateway with the copy the collector forwarded. The match-service duplicate belongs in a data-quality follow-up.
