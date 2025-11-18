import argparse
import logging
from pathlib import Path
from typing import TypedDict

import yaml


class JobInfo(TypedDict):
    workflow_name: str
    name: str


def find_workflow_files(repo_root: Path):
    """
    查找并返回仓库中 '.github/workflows' 目录下的所有 YAML 工作流文件。

    Args:
        repo_root (Path): 仓库的根目录路径。

    Returns:
        list: 包含所有工作流文件 Path 对象的列表。
    """
    workflows_path = repo_root / ".github" / "workflows"
    if not workflows_path.is_dir():
        logging.warning(f"目录不存在 {workflows_path}")
        return []
    # 同时查找 .yml 和 .yaml 后缀的文件
    return list(workflows_path.glob("*.yml")) + list(workflows_path.glob("*.yaml"))


def is_reusable_workflow(file_path: Path):
    """
    检查一个工作流文件是否是可复用的（即包含 'on: workflow_call' 触发器）。

    Args:
        file_path (Path): 要检查的工作流文件的路径。

    Returns:
        bool: 如果是可复用工作流则返回 True，否则返回 False。
    """
    try:
        with file_path.open("r", encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
            # 必须有 'on' 字段
            if not workflow or "on" not in workflow:
                return False
            on_trigger = workflow["on"]
            # 'on' 字段是一个字典，并且只包含 'workflow_call' 键
            if isinstance(on_trigger, dict) and "workflow_call" in on_trigger and len(on_trigger) == 1:
                return True
    except (yaml.YAMLError, OSError) as e:
        logging.error(f"读取或解析文件时出错 {file_path}: {e}")
    return False


def parse_workflow_jobs(file_path: Path, repo_root: Path, all_workflows: list[Path]) -> list[JobInfo]:
    """
    解析单个工作流文件，提取所有 job 信息。
    此函数会递归处理本地的可复用工作流（reusable workflows）。

    Args:
        file_path (Path): 要解析的工作流文件的路径。
        repo_root (Path): 仓库的根目录路径。
        all_workflows (list): 包含所有找到的工作流文件的列表，用于查找被调用的工作流。

    Returns:
        list[JobInfo]: 从该工作流中解析出的所有 job 信息的列表。
    """
    job_infos: list[JobInfo] = []
    try:
        with file_path.open("r", encoding="utf-8") as f:
            workflow = yaml.safe_load(f)
            # 获取工作流的名称，如果未定义，则使用文件名（不含扩展名）
            workflow_name = workflow.get("name", file_path.stem) if workflow else file_path.stem

            if not workflow or "jobs" not in workflow:
                return []

            for job_id, job_details in workflow.get("jobs", {}).items():
                # job 的显示名称，如果未定义 'name'，则使用其 ID
                job_name = job_details.get("name", job_id)

                # 检查 job 是否调用了另一个工作流
                if "uses" in job_details:
                    uses_path = job_details["uses"]
                    if uses_path.startswith("./.github/workflows/"):
                        reusable_workflow_path = Path(repo_root) / uses_path[2:]

                        # 从所有工作流文件列表中找到被调用者的完整路径
                        callee_path = None
                        for wf in all_workflows:
                            if wf.name == reusable_workflow_path.name:
                                callee_path = wf
                                break

                        if callee_path and callee_path.exists():
                            # 获取调用方 job 的名称作为前缀
                            caller_job_name = job_details.get("name", job_id)
                            # 递归解析被调用的工作流
                            sub_jobs = parse_workflow_jobs(callee_path, repo_root, all_workflows)
                            # 将调用者和被调用者的 job 名称组合起来
                            for sub_job_info in sub_jobs:
                                job_infos.append(
                                    {
                                        "workflow_name": workflow_name,
                                        "name": f"{caller_job_name} / {sub_job_info['name']}",
                                    }
                                )
                        else:
                            # 如果找不到被调用的工作流文件，则只使用当前 job 的名称
                            logging.warning(f"找不到可复用工作流 {uses_path}")
                            job_infos.append({"workflow_name": workflow_name, "name": job_name})
                    else:
                        # 对于远程工作流（如 'actions/checkout@v4'），我们无法解析其内部，
                        # 因此直接使用当前 job 的名称。
                        job_infos.append({"workflow_name": workflow_name, "name": job_name})
                else:
                    # 这是一个常规的、独立的 job
                    job_infos.append({"workflow_name": workflow_name, "name": job_name})
    except yaml.YAMLError as e:
        logging.error(f"解析 YAML 文件时出错 {file_path}: {e}")
    except Exception as e:
        logging.error(f"处理文件时发生未知错误 {file_path}: {e}")

    return job_infos


def main():
    """
    主函数，负责执行整个解析流程。
    1. 解析命令行参数。
    2. 查找所有工作流文件。
    3. 筛选出顶层工作流（非可复用工作流）。
    4. 遍历并解析每个顶层工作流。
    5. 收集并打印所有唯一的 job 信息。
    """
    parser = argparse.ArgumentParser(description="从 GitHub Actions 工作流中解析实际运行的 job 名称。")
    parser.add_argument(
        "--repo-root",
        type=str,
        default=".",
        help="仓库的根目录路径。",
    )
    parser.add_argument(
        "--only-names",
        action="store_true",
        help="只输出发现的所有 Job 名称，不包含其他信息。",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="启用详细日志记录。",
    )
    args = parser.parse_args()

    # 根据 --verbose 参数配置日志级别
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    repo_root = Path(args.repo_root).resolve()
    logging.info(f"在目录中搜索工作流文件: {repo_root / '.github' / 'workflows'}")

    all_workflow_files = find_workflow_files(repo_root)
    all_job_infos: set[tuple[str, str]] = set()  # 使用集合来自动去重

    # 筛选出顶层工作流：即那些不是被其他工作流调用的可复用工作流
    top_level_workflows = [wf for wf in all_workflow_files if not is_reusable_workflow(wf)]
    logging.info(f"找到 {len(top_level_workflows)} 个顶层工作流进行解析。")

    # 遍历每个顶层工作流并解析其中的 job
    for workflow_file in top_level_workflows:
        logging.info(f"正在解析: {workflow_file.relative_to(repo_root)}...")
        jobs = parse_workflow_jobs(workflow_file, repo_root, all_workflow_files)
        for job_info in jobs:
            all_job_infos.add((job_info["workflow_name"], job_info["name"]))

    # 打印最终结果
    print("\n--- 发现的所有 Job 信息 ---")
    for wf_name, job_name in sorted(all_job_infos):
        if args.only_names:
            print(job_name)
        else:
            print(f"{wf_name} -> {job_name}")
    print("--------------------------\n")
