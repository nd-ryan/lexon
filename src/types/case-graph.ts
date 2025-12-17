export interface GraphNode {
  temp_id: string;
  label: string;
  properties?: Record<string, unknown>;
  related?: Record<string, GraphNode>; // For catalog nodes with embedded relationships (e.g., Forum -> Jurisdiction)
  is_existing?: boolean; // Flag to indicate if this node exists in the Neo4j catalog
}

export interface GraphEdge {
  from: string;
  to: string;
  label: string;
}

export interface CaseGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  file_key?: string;
  kg_diverged?: boolean;
}

export type UiInputType =
  | 'text'
  | 'textarea'
  | 'select'
  | 'number'
  | 'date'
  | 'checkbox'
  | 'list';

export interface PropertyUi {
  input?: UiInputType;
  label?: string;
  required?: boolean;
  options?: string[];
  hidden?: boolean;
  order?: number;
  help?: string;
}

export interface SchemaPropertyDef {
  type?: string;
  ui?: PropertyUi;
}

export type RelationshipCardinality = 'one-to-one' | 'one-to-many' | 'many-to-one' | 'many-to-many';

export interface SchemaRelationship {
  target: string;
  cardinality: RelationshipCardinality;
  properties?: Record<string, SchemaPropertyDef>;
}

export interface SchemaItem {
  label: string;
  case_unique?: boolean;
  can_create_new?: boolean;
  min_per_case?: number;
  properties?: Record<string, SchemaPropertyDef>;
  attributes?: Record<string, string>;
  relationships?: Record<string, SchemaRelationship>;
}

export type Schema = SchemaItem[];


