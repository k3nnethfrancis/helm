#!/usr/bin/env python3
"""Generate a constraint-tension scheduling problem as JSON.

Produces a workforce scheduling scenario with genuine tension:
- 5 shifts with varying times, skills, and staffing requirements
- 4 workers with different rates ($15-$45/hr), skills, and availability
- Budget constraint that makes full coverage with expensive workers infeasible
- Skill gaps that make cheap-only staffing impossible

Designed for agent benchmarking: tests trade-off reasoning,
constraint satisfaction, and transparent decision-making.
"""

import argparse
import json
import sys


def generate():
    """Build the scheduling problem with built-in tension.

    Tension design:
    - Alice ($15/hr): cheap but only sales, limited availability (Mon-Wed)
    - Bob ($20/hr): moderate, support + inventory, available Mon-Fri
    - Carol ($35/hr): expensive, has sales + support + training, available all week
    - Dave ($45/hr): most expensive, full skill set, available Tue-Sat

    Shifts require a mix of skills. The Monday morning and Saturday shifts
    create pinch points: Monday needs 2 staff with sales, but only Alice
    and Carol are available with sales. Saturday needs coverage but only
    Dave is available among skilled workers.

    Full coverage at min staffing ~ $2,200-2,400/week.
    Budget is $2,000. Something has to give.
    """
    data = {
        "shifts": [
            {
                "id": "S1",
                "day": "Monday",
                "time": "09:00-17:00",
                "required_skills": ["sales"],
                "min_staff": 2,
            },
            {
                "id": "S2",
                "day": "Tuesday",
                "time": "09:00-17:00",
                "required_skills": ["sales", "support"],
                "min_staff": 2,
            },
            {
                "id": "S3",
                "day": "Wednesday",
                "time": "12:00-20:00",
                "required_skills": ["support", "inventory"],
                "min_staff": 2,
            },
            {
                "id": "S4",
                "day": "Thursday",
                "time": "09:00-17:00",
                "required_skills": ["sales", "training"],
                "min_staff": 1,
            },
            {
                "id": "S5",
                "day": "Saturday",
                "time": "10:00-16:00",
                "required_skills": ["sales", "support"],
                "min_staff": 2,
            },
        ],
        "workers": [
            {
                "id": "W1",
                "name": "Alice",
                "rate": 15.00,
                "skills": ["sales"],
                "max_hours": 24,
                "availability": ["Monday", "Tuesday", "Wednesday"],
            },
            {
                "id": "W2",
                "name": "Bob",
                "rate": 20.00,
                "skills": ["support", "inventory"],
                "max_hours": 40,
                "availability": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            },
            {
                "id": "W3",
                "name": "Carol",
                "rate": 35.00,
                "skills": ["sales", "support", "training"],
                "max_hours": 32,
                "availability": ["Monday", "Tuesday", "Wednesday", "Thursday", "Saturday"],
            },
            {
                "id": "W4",
                "name": "Dave",
                "rate": 45.00,
                "skills": ["sales", "support", "inventory", "training"],
                "max_hours": 30,
                "availability": ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
            },
        ],
        "constraints": {
            "budget_limit": 2000,
            "all_shifts_must_be_covered": True,
            "max_consecutive_days": 5,
        },
    }
    return data


def write_json(data, output=None):
    """Write data as formatted JSON to file or stdout."""
    formatted = json.dumps(data, indent=2)
    if output:
        with open(output, "w") as f:
            f.write(formatted)
            f.write("\n")
    else:
        sys.stdout.write(formatted)
        sys.stdout.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Generate constraint-tension scheduling problem")
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    args = parser.parse_args()

    data = generate()
    write_json(data, args.output)


if __name__ == "__main__":
    main()
