import argparse
import logging
from pathlib import Path
from typing import TypedDict

import yaml


class JobInfo(TypedDict):
    workflow_name: str
    name: str


def find_workflow_files(repo_root: Path) -> list[Path]:
    """Finds all GitHub Actions workflow files in a repository.

    Args:
        repo_root: The root path of the repository.

    Returns:
        A list of paths to all found workflow files (.yml and .yaml).
        Returns an empty list if the '.github/workflows' directory is not found.
    """
    workflows_path = repo_root / ".github" / "workflows"
    if not workflows_path.is_dir():
        logging.warning(f"Workflows directory does not exist: {workflows_path}")
        return []
    return list(workflows_path.glob("*.yml")) + list(workflows_path.glob("*.yaml"))


def is_reusable_workflow(file_path: Path) -> bool:
    """Checks if a workflow is purely a reusable workflow.

    A workflow is considered purely reusable if its 'on' trigger only
    contains 'workflow_call'.

    Args:
        file_path: The path to the workflow file to check.

    Returns:
        True if the workflow is purely reusable, False otherwise.
        Also returns False if there is an error reading or parsing the file.
    """
    try:
        with file_path.open("r", encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
            # The 'on' trigger must be present.
            if not workflow or "on" not in workflow:
                return False
            on_trigger = workflow["on"]
            # The 'on' trigger must be a dictionary containing only 'workflow_call'.
            if isinstance(on_trigger, dict) and "workflow_call" in on_trigger and len(on_trigger) == 1:
                return True
    except (yaml.YAMLError, OSError) as e:
        logging.error(f"Error reading or parsing file {file_path}: {e}")
    return False


def parse_workflow_jobs(
    file_path: Path,
    repo_root: Path,
) -> list[JobInfo]:
    """Parses a single workflow file to extract all job information.

    This function recursively handles local reusable workflows.

    Args:
        file_path: The path to the workflow file to parse.
        repo_root: The root path of the repository.

    Returns:
        A list of JobInfo objects parsed from the workflow.
    """
    job_infos: list[JobInfo] = []
    try:
        with file_path.open("r", encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
            # Get the workflow name, or use the filename (without extension) if not defined.
            workflow_name = workflow.get("name", file_path.stem) if workflow else file_path.stem

            if not workflow or "jobs" not in workflow:
                return []

            for job_id, job_details in workflow.get("jobs", {}).items():
                # Use the job's display name, or its ID if 'name' is not defined.
                job_name = job_details.get("name", job_id)

                # Check if the job calls another workflow.
                if "uses" in job_details:
                    uses_path = job_details["uses"]
                    if uses_path.startswith("./.github/workflows/"):
                        reusable_workflow_path = Path(repo_root) / uses_path

                        if reusable_workflow_path.exists():
                            caller_job_name = job_details.get("name", job_id)
                            # Recursively parse the called workflow.
                            sub_jobs = parse_workflow_jobs(
                                reusable_workflow_path,
                                repo_root,
                            )
                            # Combine the caller and callee job names.
                            for sub_job_info in sub_jobs:
                                job_infos.append(
                                    {
                                        "workflow_name": workflow_name,
                                        "name": f"{caller_job_name} / {sub_job_info['name']}",
                                    }
                                )
                        else:
                            # If the called workflow file is not found, use the current job's name.
                            logging.warning(f"Reusable workflow not found: {uses_path}")
                            job_infos.append({"workflow_name": workflow_name, "name": job_name})
                    else:
                        # For remote workflows (e.g., 'actions/checkout@v4'), we can't parse them internally,
                        # so we just use the current job's name.
                        job_infos.append({"workflow_name": workflow_name, "name": job_name})
                else:
                    # This is a regular, standalone job.
                    job_infos.append({"workflow_name": workflow_name, "name": job_name})
    except yaml.YAMLError as e:
        logging.error(f"Error parsing YAML file {file_path}: {e}")
    except Exception as e:
        logging.error(f"An unknown error occurred while processing file {file_path}: {e}")

    return job_infos


def main():
    """
    The main function responsible for the entire parsing process.
    1. Parses command-line arguments.
    2. Finds all workflow files.
    3. Filters for top-level (non-reusable) workflows.
    4. Iterates through and parses each top-level workflow.
    5. Collects and prints all unique job information.
    """
    parser = argparse.ArgumentParser(description="Parse effective job names from GitHub Actions workflows.")
    parser.add_argument(
        "--repo-root",
        type=str,
        default=".",
        help="The root path of the repository.",
    )
    parser.add_argument(
        "--only-names",
        action="store_true",
        help="Only output the names of all discovered jobs, without extra info.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed logging.",
    )
    args = parser.parse_args()

    # Configure logging level based on --verbose argument
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    repo_root = Path(args.repo_root).resolve()
    logging.info(f"Searching for workflow files in: {repo_root / '.github' / 'workflows'}")

    all_workflow_files = find_workflow_files(repo_root)
    all_job_infos: set[tuple[str, str]] = set()  # Use a set to automatically handle duplicates

    # Filter for top-level workflows: those that are not purely reusable.
    top_level_workflows = [wf for wf in all_workflow_files if not is_reusable_workflow(wf)]
    logging.info(f"Found {len(top_level_workflows)} top-level workflows to parse.")

    # Iterate through each top-level workflow and parse its jobs
    for workflow_file in top_level_workflows:
        if not args.only_names:
            logging.info(f"Parsing: {workflow_file.relative_to(repo_root)}...")
        jobs = parse_workflow_jobs(workflow_file, repo_root)
        for job_info in jobs:
            all_job_infos.add((job_info["workflow_name"], job_info["name"]))

    # Print the final results
    if not args.only_names:
        print("\n--- All Discovered Job Info ---")
    for wf_name, job_name in sorted(all_job_infos):
        if args.only_names:
            print(job_name)
        else:
            print(f"{wf_name} -> {job_name}")
    if not args.only_names:
        print("---------------------------\n")
