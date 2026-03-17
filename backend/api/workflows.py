"""
Workflows API endpoints
Create and manage analysis workflows
"""
from fastapi import APIRouter, HTTPException, Body, Depends, Query
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime
import uuid
import asyncio
import time

from models.schemas import Workflow, WorkflowStep, AgentType
from models.database import WorkflowExecution
from services.agent_orchestrator import AgentOrchestrator
from core.database import get_db
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory storage for demo
workflows_store = {}
workflow_results_store = {}  # Store workflow execution results

# Global orchestrator instance (will be initialized)
orchestrator: Optional[AgentOrchestrator] = None


def set_orchestrator(orch: AgentOrchestrator):
    """Set the orchestrator instance for workflow execution"""
    global orchestrator
    orchestrator = orch


@router.post("/", response_model=Workflow)
async def create_workflow(workflow_data: dict):
    """
    Create a new workflow
    
    Args:
        workflow_data: Workflow definition
        
    Returns:
        Created workflow
    """
    try:
        workflow_id = str(uuid.uuid4())
        
        # Convert steps to WorkflowStep objects if they're dicts
        steps = []
        for step_data in workflow_data.get("steps", []):
            if isinstance(step_data, dict):
                # Convert dict to WorkflowStep
                agent_type_str = step_data.get("agent_type", "")
                if isinstance(agent_type_str, str):
                    agent_type_map = {
                        "data_curation": AgentType.DATA_CURATION,
                        "statistical_analysis": AgentType.STATISTICAL_ANALYSIS,
                        "visualization": AgentType.VISUALIZATION,
                        "literature_mining": AgentType.LITERATURE_MINING
                    }
                    agent_type = agent_type_map.get(agent_type_str.lower(), AgentType.DATA_CURATION)
                else:
                    agent_type = agent_type_str  # Already an enum
                
                steps.append(WorkflowStep(
                    step_id=step_data.get("step_id", f"step_{len(steps) + 1}"),
                    agent_type=agent_type,
                    action=step_data.get("action", ""),
                    parameters=step_data.get("parameters", {}),
                    dependencies=step_data.get("dependencies", []),
                    status="pending"
                ))
            else:
                # Already a WorkflowStep object
                steps.append(step_data)
        
        workflow = Workflow(
            id=workflow_id,
            name=workflow_data.get("name", "New Workflow"),
            description=workflow_data.get("description", ""),
            steps=steps,
            created_at=datetime.now(),
            status="pending"
        )
        
        workflows_store[workflow_id] = workflow
        logger.info(f"Created workflow: {workflow_id} with {len(steps)} steps")
        return workflow
        
    except Exception as e:
        logger.error(f"Error creating workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}", response_model=Workflow)
async def get_workflow(workflow_id: str):
    """
    Get workflow by ID
    
    Args:
        workflow_id: Workflow identifier
        
    Returns:
        Workflow details
    """
    try:
        if workflow_id not in workflows_store:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        return workflows_store[workflow_id]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=List[Workflow])
async def list_workflows(status: Optional[str] = None):
    """
    List all workflows
    
    Args:
        status: Filter by status
        
    Returns:
        List of workflows
    """
    try:
        workflows = list(workflows_store.values())
        
        if status:
            workflows = [w for w in workflows if w.status == status]
        
        return workflows
        
    except Exception as e:
        logger.error(f"Error listing workflows: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    parameters: Optional[Dict[str, Any]] = Body(None),
    db: Session = Depends(get_db)
):
    """
    Execute a workflow
    
    Args:
        workflow_id: Workflow identifier
        parameters: Optional parameters to override workflow step parameters
        
    Returns:
        Execution status and results
    """
    try:
        if workflow_id not in workflows_store:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        if orchestrator is None:
            raise HTTPException(
                status_code=500,
                detail="Orchestrator not initialized. Please ensure agents are initialized."
            )
        
        workflow = workflows_store[workflow_id]
        
        # Check if workflow is already running
        if workflow.status == "running":
            raise HTTPException(
                status_code=400,
                detail="Workflow is already running"
            )
        
        # Reset workflow status for new execution (allows re-running)
        workflow.status = "running"
        for step in workflow.steps:
            step.status = "pending"
        
        # Create execution record in database
        execution_id = str(uuid.uuid4())
        execution_record = WorkflowExecution(
            id=execution_id,
            workflow_id=workflow_id,
            workflow_name=workflow.name,
            status="running",
            parameters=parameters or {},
            started_at=time.time(),
            completed_at=None
        )
        db.add(execution_record)
        db.commit()
        db.refresh(execution_record)
        
        # Log parameters being used
        logger.info(f"Executing workflow {workflow_id} (execution {execution_id}) with parameters: {parameters}")
        if not parameters or len(parameters) == 0:
            logger.warning(f"Workflow {workflow_id} executing with NO user-provided parameters - will use default/placeholder values")
        
        # Execute workflow asynchronously (pass execution_id)
        # Note: We'll get a new db session inside the async task
        execution_task = asyncio.create_task(
            _execute_workflow_steps(workflow, parameters or {}, execution_id)
        )
        
        return {
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "status": "running",
            "message": "Workflow execution started",
            "steps_count": len(workflow.steps),
            "parameters_used": parameters or {}
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing workflow: {e}")
        if workflow_id in workflows_store:
            workflows_store[workflow_id].status = "failed"
        raise HTTPException(status_code=500, detail=str(e))


async def _execute_workflow_steps(
    workflow: Workflow,
    override_parameters: Dict[str, Any],
    execution_id: str
) -> Dict[str, Any]:
    """
    Execute workflow steps in dependency order
    
    Args:
        workflow: Workflow to execute
        override_parameters: Parameters to override step parameters
        
    Returns:
        Execution results
    """
    step_results = {}
    execution_order = _determine_execution_order(workflow.steps)
    
    try:
        # Create a session for the workflow
        import time
        session = {
            "id": f"workflow_{workflow.id}",
            "user_id": "workflow_user",
            "title": workflow.name,
            "history": [],
            "context": {},
            "created_at": time.time(),
            "last_updated": time.time()
        }
        
        # Execute steps in order
        for step_index in execution_order:
            step = workflow.steps[step_index]
            
            try:
                # Update step status
                step.status = "running"
                logger.info(f"Executing workflow step: {step.step_id} ({step.agent_type})")
                
                # Get dependency results
                dependency_results = {}
                for dep_step_id in step.dependencies:
                    # Find the step index
                    dep_index = next(
                        (i for i, s in enumerate(workflow.steps) if s.step_id == dep_step_id),
                        None
                    )
                    if dep_index is not None and dep_index in step_results:
                        dependency_results[dep_step_id] = step_results[dep_index]
                
                # Also add all previous step results for context (especially for visualization agent)
                # This allows visualization agent to access analysis results
                all_previous_results = {}
                for prev_idx, prev_result in step_results.items():
                    if isinstance(prev_idx, int) and prev_idx < step_index:
                        # Get the step_id for this result
                        prev_step = workflow.steps[prev_idx]
                        all_previous_results[prev_step.step_id] = prev_result
                        # Also add by agent name for easier access
                        if isinstance(prev_result, dict) and "agent" in prev_result:
                            all_previous_results[prev_result["agent"]] = prev_result
                
                # Merge parameters (override takes precedence)
                # First, merge workflow-level user parameters (like gene_name, cancer_type)
                step_params = {**step.parameters}
                # User-provided parameters at workflow level (e.g., gene_name, cancer_type)
                # should be available to all steps
                for key, value in override_parameters.items():
                    if key not in ["step_1", "step_2", "step_3", "step_4", "step_5", "step_6"]:
                        # This is a workflow-level parameter, add it to all steps
                        step_params[key] = value
                # Step-specific overrides (e.g., override_parameters["step_1"]["data_type"])
                if step.step_id in override_parameters:
                    step_params.update(override_parameters[step.step_id])
                
                # Build action string from step, substituting user parameters
                action = _build_action_string(step.action, step_params)
                
                # Log what action and parameters are being used
                logger.info(f"Step {step.step_id} action: {action}")
                logger.info(f"Step {step.step_id} parameters: {step_params}")
                
                # Build context
                context = {
                    "query": f"Workflow: {workflow.name} - {action}",
                    "session": session,
                    "previous_results": {**dependency_results, **all_previous_results},  # Merge both dependency and all previous results
                    "workflow_step": step.step_id,
                    "parameters": step_params,
                    "data": all_previous_results  # Also add as 'data' for easier access
                }
                
                # Map agent type to agent name
                agent_name = _map_agent_type_to_name(step.agent_type)
                
                # Execute agent
                if agent_name in orchestrator.agents:
                    agent = orchestrator.agents[agent_name]
                    result = await agent.process(action, context)
                    
                    step_results[step_index] = result
                    step.status = "completed"
                    logger.info(f"Completed workflow step: {step.step_id}")
                else:
                    raise ValueError(f"Agent {agent_name} not found")
                    
            except Exception as e:
                logger.error(f"Error executing step {step.step_id}: {e}")
                step.status = "failed"
                step_results[step_index] = {
                    "success": False,
                    "error": str(e)
                }
                # Continue with other steps (don't fail entire workflow)
        
        # Update workflow status
        all_completed = all(s.status == "completed" for s in workflow.steps)
        any_failed = any(s.status == "failed" for s in workflow.steps)
        
        if any_failed:
            workflow.status = "partially_completed"
        elif all_completed:
            workflow.status = "completed"
        else:
            workflow.status = "failed"
        
        # Generate summary
        summary = _generate_workflow_summary(workflow, step_results)
        
        # Store results in database (get new db session for async task)
        from core.database import SessionLocal
        db = SessionLocal()
        try:
            execution_record = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()
            if execution_record:
                execution_record.status = workflow.status
                execution_record.step_results = step_results
                execution_record.summary = summary
                execution_record.completed_at = time.time()
                db.commit()
                logger.info(f"Saved workflow execution {execution_id} to database")
        except Exception as e:
            logger.error(f"Error saving execution to database: {e}")
            db.rollback()
        finally:
            db.close()
        
        # Also keep in-memory store for backward compatibility
        execution_results = {
            "workflow_id": workflow.id,
            "status": workflow.status,
            "step_results": step_results,
            "summary": summary,
            "completed_at": datetime.now().isoformat()
        }
        workflow_results_store[workflow.id] = execution_results
        
        # Keep workflow status as completed/failed so UI can show final state
        # Status will be reset to "ready" when a new execution starts
        # Don't reset steps status either - keep them showing completed/failed
        logger.info(f"Workflow {workflow.id} execution {execution_id} completed with status: {workflow.status}")
        
        return execution_results
        
    except Exception as e:
        logger.error(f"Error in workflow execution: {e}")
        workflow.status = "failed"
        
        # Update database record with error (get new db session for async task)
        from core.database import SessionLocal
        db = SessionLocal()
        try:
            execution_record = db.query(WorkflowExecution).filter(WorkflowExecution.id == execution_id).first()
            if execution_record:
                execution_record.status = "failed"
                execution_record.error_message = str(e)
                execution_record.completed_at = time.time()
                db.commit()
        except Exception as db_error:
            logger.error(f"Error updating execution record: {db_error}")
            db.rollback()
        finally:
            db.close()
        
        # Store error result in-memory
        workflow_results_store[workflow.id] = {
            "workflow_id": workflow.id,
            "status": "failed",
            "error": str(e),
            "step_results": step_results if 'step_results' in locals() else {}
        }
        
        # Reset workflow status to "ready" so it can be run again
        workflow.status = "ready"
        
        raise


def _determine_execution_order(steps: List[WorkflowStep]) -> List[int]:
    """
    Determine the order to execute steps based on dependencies
    
    Returns:
        List of step indices in execution order
    """
    # Build dependency graph
    step_index_map = {step.step_id: i for i, step in enumerate(steps)}
    dependencies = {i: [] for i in range(len(steps))}
    dependents = {i: [] for i in range(len(steps))}
    
    for i, step in enumerate(steps):
        for dep_step_id in step.dependencies:
            dep_index = step_index_map.get(dep_step_id)
            if dep_index is not None:
                dependencies[i].append(dep_index)
                dependents[dep_index].append(i)
    
    # Topological sort
    execution_order = []
    ready = [i for i in range(len(steps)) if not dependencies[i]]
    in_degree = {i: len(dependencies[i]) for i in range(len(steps))}
    
    while ready:
        step_index = ready.pop(0)
        execution_order.append(step_index)
        
        # Update dependents
        for dependent in dependents[step_index]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)
    
    # Check for cycles
    if len(execution_order) != len(steps):
        logger.warning("Workflow has circular dependencies or missing step references")
        # Fallback: execute in order
        execution_order = list(range(len(steps)))
    
    return execution_order


def _map_agent_type_to_name(agent_type: AgentType) -> str:
    """Map AgentType enum to agent name used in orchestrator"""
    mapping = {
        AgentType.DATA_CURATION: "data",
        AgentType.STATISTICAL_ANALYSIS: "analysis",
        AgentType.VISUALIZATION: "visualization",
        AgentType.LITERATURE_MINING: "literature"
    }
    return mapping.get(agent_type, "data")


def _build_action_string(action: str, parameters: Dict[str, Any]) -> str:
    """
    Build action string from step action and parameters.
    Substitutes user-provided values into the action template.
    """
    formatted_action = action
    
    # Replace placeholders in the action string with actual values
    # e.g., "find datasets for specified cancer type" -> "find datasets for breast cancer"
    if "specified cancer type" in formatted_action.lower() and "cancer_type" in parameters:
        formatted_action = formatted_action.replace("specified cancer type", str(parameters["cancer_type"]))
        formatted_action = formatted_action.replace("Specified cancer type", str(parameters["cancer_type"]))
    
    if "target gene" in formatted_action.lower():
        gene_name = parameters.get("gene_name") or parameters.get("target_gene")
        if gene_name:
            formatted_action = formatted_action.replace("target gene", str(gene_name))
            formatted_action = formatted_action.replace("Target gene", str(gene_name))
    
    # Also append parameters for clarity (but don't duplicate if already in action)
    if parameters:
        # Filter out parameters that were already substituted
        remaining_params = {k: v for k, v in parameters.items() 
                          if k not in ["cancer_type", "gene_name", "target_gene"] 
                          or (k in ["cancer_type", "gene_name", "target_gene"] 
                              and str(v) not in formatted_action)}
        if remaining_params:
            param_str = ", ".join([f"{k}={v}" for k, v in remaining_params.items()])
            formatted_action = f"{formatted_action} ({param_str})"
    
    return formatted_action


def _generate_workflow_summary(
    workflow: Workflow,
    step_results: Dict[int, Dict[str, Any]]
) -> str:
    """Generate a summary of workflow execution"""
    completed = sum(1 for s in workflow.steps if s.status == "completed")
    failed = sum(1 for s in workflow.steps if s.status == "failed")
    
    summary = f"Workflow '{workflow.name}' execution completed.\n"
    summary += f"Steps: {completed} completed, {failed} failed out of {len(workflow.steps)} total.\n\n"
    
    for i, step in enumerate(workflow.steps):
        status_icon = "✅" if step.status == "completed" else "❌" if step.status == "failed" else "⏳"
        summary += f"{status_icon} {step.step_id}: {step.action} ({step.status})\n"
    
    return summary


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """
    Delete a workflow
    
    Args:
        workflow_id: Workflow identifier
        
    Returns:
        Success message
    """
    try:
        if workflow_id not in workflows_store:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        del workflows_store[workflow_id]
        return {"message": "Workflow deleted", "id": workflow_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}/executions")
async def list_workflow_executions(
    workflow_id: str,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    List execution history for a workflow
    
    Args:
        workflow_id: Workflow identifier
        limit: Maximum number of executions to return
        
    Returns:
        List of execution records
    """
    try:
        executions = db.query(WorkflowExecution).filter(
            WorkflowExecution.workflow_id == workflow_id
        ).order_by(WorkflowExecution.started_at.desc()).limit(limit).all()
        
        return {
            "workflow_id": workflow_id,
            "executions": [
                {
                    "execution_id": e.id,
                    "status": e.status,
                    "started_at": e.started_at * 1000,  # Convert to milliseconds
                    "completed_at": e.completed_at * 1000 if e.completed_at else None,
                    "parameters": e.parameters,
                    "summary": e.summary,
                    "error_message": e.error_message
                }
                for e in executions
            ]
        }
    except Exception as e:
        logger.error(f"Error listing workflow executions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}/results")
async def get_workflow_results(
    workflow_id: str,
    execution_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Get workflow execution results
    
    Args:
        workflow_id: Workflow identifier
        execution_id: Optional execution ID (query parameter)
        
    Returns:
        Workflow execution results including step results
    """
    """
    Get workflow execution results
    
    Args:
        workflow_id: Workflow identifier
        
    Returns:
        Workflow execution results including step results
    """
    try:
        if workflow_id not in workflows_store:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # If execution_id is provided, get that specific execution
        if execution_id:
            execution = db.query(WorkflowExecution).filter(
                WorkflowExecution.id == execution_id,
                WorkflowExecution.workflow_id == workflow_id
            ).first()
            if not execution:
                raise HTTPException(status_code=404, detail="Execution not found")
            
            # Handle JSON deserialization - SQLAlchemy JSON columns return dict/None
            step_results = execution.step_results if execution.step_results is not None else {}
            if isinstance(step_results, str):
                import json as json_lib
                step_results = json_lib.loads(step_results)
            # Convert string keys to integers (JSON stores numeric keys as strings)
            if isinstance(step_results, dict):
                converted_results = {}
                for k, v in step_results.items():
                    try:
                        # Try to convert string keys that look like integers
                        if isinstance(k, str) and k.isdigit():
                            converted_results[int(k)] = v
                        elif isinstance(k, int):
                            converted_results[k] = v
                        else:
                            # Keep non-numeric keys as-is
                            converted_results[k] = v
                    except (ValueError, TypeError):
                        converted_results[k] = v
                step_results = converted_results
            
            results = {
                "workflow_id": workflow_id,
                "execution_id": execution_id,
                "status": execution.status,
                "step_results": step_results,
                "summary": execution.summary,
                "completed_at": execution.completed_at * 1000 if execution.completed_at else None,
                "parameters": execution.parameters
            }
        # Otherwise, get the most recent execution
        else:
            latest_execution = db.query(WorkflowExecution).filter(
                WorkflowExecution.workflow_id == workflow_id
            ).order_by(WorkflowExecution.started_at.desc()).first()
            
            if not latest_execution:
                # Fallback to in-memory store for backward compatibility
                if workflow_id not in workflow_results_store:
                    return {
                        "workflow_id": workflow_id,
                        "status": "no_results",
                        "message": "Workflow has not been executed yet or execution is still in progress"
                    }
                results = workflow_results_store[workflow_id]
            else:
                # Handle JSON deserialization
                step_results = latest_execution.step_results if latest_execution.step_results is not None else {}
                if isinstance(step_results, str):
                    import json as json_lib
                    step_results = json_lib.loads(step_results)
                # Convert string keys to integers (JSON stores numeric keys as strings)
                if isinstance(step_results, dict):
                    converted_results = {}
                    for k, v in step_results.items():
                        try:
                            # Try to convert string keys that look like integers
                            if isinstance(k, str) and k.isdigit():
                                converted_results[int(k)] = v
                            elif isinstance(k, int):
                                converted_results[k] = v
                            else:
                                # Keep non-numeric keys as-is
                                converted_results[k] = v
                        except (ValueError, TypeError):
                            converted_results[k] = v
                    step_results = converted_results
                
                results = {
                    "workflow_id": workflow_id,
                    "execution_id": latest_execution.id,
                    "status": latest_execution.status,
                    "step_results": step_results,
                    "summary": latest_execution.summary,
                    "completed_at": latest_execution.completed_at * 1000 if latest_execution.completed_at else None,
                    "parameters": latest_execution.parameters
                }
        
        # Format step results for better readability
        formatted_results = {
            "workflow_id": workflow_id,
            "workflow_name": workflows_store[workflow_id].name,
            "status": results.get("status", "unknown"),
            "summary": results.get("summary", ""),
            "completed_at": results.get("completed_at"),
            "steps": []
        }
        
        # Add step details with results
        step_results_dict = results.get("step_results", {})
        logger.info(f"Step results keys (before formatting): {list(step_results_dict.keys())}")
        logger.info(f"Step results type: {type(step_results_dict)}")
        
        for i, step in enumerate(workflows_store[workflow_id].steps):
            # Try both integer and string key (JSON may store as string)
            step_result = step_results_dict.get(i) or step_results_dict.get(str(i), {})
            if not step_result:
                logger.warning(f"No result found for step {i} (step_id: {step.step_id})")
            formatted_results["steps"].append({
                "step_id": step.step_id,
                "agent_type": step.agent_type.value,
                "action": step.action,
                "status": step.status,
                "result": step_result
            })
        
        return formatted_results
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting workflow results: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}/status")
async def get_workflow_status(workflow_id: str):
    """
    Get workflow execution status
    
    Args:
        workflow_id: Workflow identifier
        
    Returns:
        Workflow status and step statuses
    """
    try:
        if workflow_id not in workflows_store:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        workflow = workflows_store[workflow_id]
        
        return {
            "workflow_id": workflow_id,
            "status": workflow.status,
            "steps": [
                {
                    "step_id": step.step_id,
                    "status": step.status,
                    "action": step.action,
                    "agent_type": step.agent_type.value
                }
                for step in workflow.steps
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting workflow status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/templates/{template_name}")
async def create_workflow_from_template(template_name: str):
    """
    Create workflow from a predefined template
    
    Args:
        template_name: Name of the template (correlation_analysis, survival_analysis, etc.)
        
    Returns:
        Created workflow
    """
    try:
        from examples.example_workflows import EXAMPLE_WORKFLOWS
        
        if template_name not in EXAMPLE_WORKFLOWS:
            raise HTTPException(
                status_code=404,
                detail=f"Template '{template_name}' not found. Available: {list(EXAMPLE_WORKFLOWS.keys())}"
            )
        
        template = EXAMPLE_WORKFLOWS[template_name]
        
        # Convert template format to Workflow schema
        workflow_steps = []
        for step_data in template["steps"]:
            # Map agent type string to enum
            agent_type_map = {
                "data_curation": AgentType.DATA_CURATION,
                "statistical_analysis": AgentType.STATISTICAL_ANALYSIS,
                "visualization": AgentType.VISUALIZATION,
                "literature_mining": AgentType.LITERATURE_MINING
            }
            
            agent_type_str = step_data.get("agent_type", "").lower()
            agent_type = agent_type_map.get(agent_type_str, AgentType.DATA_CURATION)
            
            workflow_steps.append(WorkflowStep(
                step_id=step_data["step_id"],
                agent_type=agent_type,
                action=step_data["action"],
                parameters=step_data.get("parameters", {}),
                dependencies=step_data.get("dependencies", []),
                status="pending"
            ))
        
        workflow_data = {
            "name": template["name"],
            "description": template.get("description", ""),
            "steps": workflow_steps
        }
        
        return await create_workflow(workflow_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating workflow from template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/seed-examples")
async def seed_example_workflows():
    """
    Seed example workflows from templates
    
    Returns:
        List of created workflows
    """
    try:
        from examples.example_workflows import EXAMPLE_WORKFLOWS
        
        created_workflows = []
        skipped_workflows = []
        
        for template_name in EXAMPLE_WORKFLOWS.keys():
            try:
                # Check if a workflow with this name already exists
                template_data = EXAMPLE_WORKFLOWS[template_name]
                workflow_name = template_data.get("name", template_name)
                
                # Check if workflow already exists in the store
                existing_workflow = None
                for wf_id, wf in workflows_store.items():
                    if wf.name == workflow_name:
                        existing_workflow = wf
                        break
                
                if existing_workflow:
                    logger.info(f"Workflow '{workflow_name}' already exists, skipping")
                    skipped_workflows.append(workflow_name)
                    continue
                
                # Create new workflow if it doesn't exist
                workflow = await create_workflow_from_template(template_name)
                created_workflows.append(workflow)
            except Exception as e:
                logger.warning(f"Failed to create workflow from template {template_name}: {e}")
        
        message = f"Created {len(created_workflows)} new workflow(s)"
        if skipped_workflows:
            message += f", skipped {len(skipped_workflows)} existing workflow(s)"
        
        return {
            "message": message,
            "workflows": created_workflows,
            "skipped": skipped_workflows
        }
        
    except Exception as e:
        logger.error(f"Error seeding example workflows: {e}")
        raise HTTPException(status_code=500, detail=str(e))
