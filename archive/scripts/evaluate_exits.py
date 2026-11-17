import argparse

from src.database import initialize_database, rows
from src.exit_metrics import format_exit_evaluation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Avalia a coorte forward do exit-engine-v1.")
    parser.add_argument("--experiment-id", type=int)
    args = parser.parse_args(argv)
    initialize_database()
    experiment_id = args.experiment_id
    if experiment_id is None:
        latest = rows("SELECT id FROM exit_experiments ORDER BY id DESC LIMIT 1")
        if not latest:
            print("Nenhum experimento do exit engine foi ativado.")
            return 0
        experiment_id = latest[0]["id"]
    print(format_exit_evaluation(experiment_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
