from pydantic import BaseModel, Field, FiniteFloat, RootModel, model_validator


class Resource(BaseModel):
    id: str = Field(min_length=1)
    label: str | None = None


class ResourcePage(BaseModel):
    items: list[Resource]
    total_items: int = Field(alias="totalItems", ge=0)


class NavigationGoal(Resource):
    name: str | None = None


class TargetConfig(BaseModel):
    name: str = Field(min_length=1)


class Action(Resource):
    config: TargetConfig


class MissionTasks(RootModel[list[Resource]]):
    pass


class WaypointPose(BaseModel):
    id: str = Field(min_length=1)
    frame_id: str = Field(alias="frameId")
    map_id: str = Field(alias="mapId")
    position_x: FiniteFloat = Field(alias="positionX")
    position_y: FiniteFloat = Field(alias="positionY")
    position_z: FiniteFloat = Field(alias="positionZ")

    @property
    def position(self) -> tuple[float, float, float]:
        return self.position_x, self.position_y, self.position_z


class NodeReference(BaseModel):
    id: str = Field(min_length=1)


class WaypointEdge(BaseModel):
    start_pose: NodeReference = Field(alias="startPose")
    end_pose: NodeReference = Field(alias="endPose")


class WaypointGraph(BaseModel):
    nodes: list[WaypointPose] = Field(min_length=1)
    edges: list[WaypointEdge] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> WaypointGraph:
        node_ids = {node.id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("Waypoint node IDs must be unique")
        for edge in self.edges:
            if edge.start_pose.id not in node_ids or edge.end_pose.id not in node_ids:
                raise ValueError("Waypoint edge references a missing node")
        return self
