from pydantic import BaseModel

from app.models.workflow import Workflow


class ExplainWorkflowRequest(BaseModel):
    workflow: Workflow


class ExplainWorkflowResponse(BaseModel):
    markdown: str
