import re
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from io import BytesIO
import mammoth

logger = logging.getLogger(__name__)

@dataclass 
class KnowledgeGraph:
    """Knowledge graph data structure."""
    cases: List[Dict[str, Any]] = field(default_factory=list)
    parties: List[Dict[str, Any]] = field(default_factory=list)
    provisions: List[Dict[str, Any]] = field(default_factory=list)
    doctrines: List[Dict[str, Any]] = field(default_factory=list)
    arguments: List[Dict[str, Any]] = field(default_factory=list)
    allegations: List[Dict[str, Any]] = field(default_factory=list)
    rulings: List[Dict[str, Any]] = field(default_factory=list)
    reliefs: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    
    # Relationships
    case_parties: List[Dict[str, str]] = field(default_factory=list)
    case_provisions: List[Dict[str, str]] = field(default_factory=list)
    case_allegations: List[Dict[str, str]] = field(default_factory=list)
    allegation_targets: List[Dict[str, str]] = field(default_factory=list)
    case_arguments: List[Dict[str, str]] = field(default_factory=list)
    argument_submitters: List[Dict[str, str]] = field(default_factory=list)
    argument_doctrines: List[Dict[str, str]] = field(default_factory=list)
    case_rulings: List[Dict[str, str]] = field(default_factory=list)
    ruling_doctrines: List[Dict[str, str]] = field(default_factory=list)
    case_reliefs: List[Dict[str, str]] = field(default_factory=list)
    evidence_in_cases: List[Dict[str, str]] = field(default_factory=list)

SECTIONS = [
    'Case', 'Parties', 'Legal Provisions',
    'Legal Doctrines', 'Arguments', 'Allegations',
    'Ruling', 'Relief', 'Evidence'
]

def parse_docx_to_knowledge_graph(file_content: bytes) -> KnowledgeGraph:
    """
    Parse a Word document (.docx) into a structured knowledge graph.
    
    Args:
        file_content: Raw bytes of the .docx file
        
    Returns:
        KnowledgeGraph object containing structured data
        
    Raises:
        Exception: If parsing fails
    """
    try:
        # Extract text from docx
        with BytesIO(file_content) as docx_stream:
            result = mammoth.extract_raw_text(docx_stream)
            raw_text = result.value
        
        # Split into lines and clean
        lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
        
        kg = KnowledgeGraph()
        
        # Maps to store unique entities
        parties_map = {}
        provisions_map = {}
        doctrines_map = {}
        
        # Current context variables
        current_section = None
        current_case = None
        current_party = None
        current_provision = None
        current_doctrine = None
        current_argument = None
        current_allegation = None
        current_ruling = None
        current_relief = None
        current_evidence = None
        
        def flush_case():
            """Add current case to the knowledge graph."""
            if current_case:
                kg.cases.append(current_case.copy())
        
        for line in lines:
            # Check for new case
            if line.startswith('🔸 Case:'):
                flush_case()
                current_case = {}
                current_section = None
                continue
            
            # Check for section headers
            if line in SECTIONS:
                current_section = line
                continue
            
            # Skip lines without key-value pairs
            if ':' not in line:
                continue
            
            # Parse key-value pairs
            parts = line.split(':', 1)
            if len(parts) != 2:
                continue
            
            key = parts[0].strip()
            value = parts[1].strip()
            
            # Process based on current section
            if current_section == 'Case':
                if current_case is not None:
                    current_case[key] = value
            
            elif current_section == 'Parties':
                if key == 'party_id':
                    party_id = re.search(r'\d+', value)
                    party_id = party_id.group() if party_id else value
                    
                    current_party = parties_map.get(party_id, {'party_id': party_id})
                    parties_map[party_id] = current_party
                    
                    # Create relationship with current case
                    if current_case and 'case_id' in current_case:
                        kg.case_parties.append({
                            'case_id': current_case['case_id'],
                            'party_id': party_id,
                            'role': None
                        })
                
                elif key in ['party_name', 'party_type'] and current_party:
                    current_party[key] = value
                
                elif key == 'role' and current_party:
                    # Update the role in the relationship
                    for rel in kg.case_parties:
                        if (rel['case_id'] == current_case.get('case_id') and 
                            rel['party_id'] == current_party['party_id']):
                            rel['role'] = value
                            break
            
            elif current_section == 'Legal Provisions':
                if key == 'provision_id':
                    provision_id = re.search(r'\d+', value)
                    provision_id = provision_id.group() if provision_id else value
                    
                    current_provision = provisions_map.get(provision_id, {'provision_id': provision_id})
                    provisions_map[provision_id] = current_provision
                    
                    # Create relationship with current case
                    if current_case and 'case_id' in current_case:
                        kg.case_provisions.append({
                            'case_id': current_case['case_id'],
                            'provision_id': provision_id
                        })
                
                elif key in ['provision_name', 'provision_statute', 'provision_text'] and current_provision:
                    current_provision[key] = value
            
            elif current_section == 'Legal Doctrines':
                if key == 'doctrine_id':
                    doctrine_id = re.search(r'\w+', value)
                    doctrine_id = doctrine_id.group() if doctrine_id else value
                    
                    current_doctrine = doctrines_map.get(doctrine_id, {'doctrine_id': doctrine_id})
                    doctrines_map[doctrine_id] = current_doctrine
                    
                    # Create relationships
                    if current_argument:
                        kg.argument_doctrines.append({
                            'argument_id': current_argument['argument_id'],
                            'doctrine_id': doctrine_id
                        })
                    
                    if current_ruling:
                        kg.ruling_doctrines.append({
                            'ruling_id': current_ruling['ruling_id'],
                            'doctrine_id': doctrine_id
                        })
                
                elif key in ['doctrine_name', 'description'] and current_doctrine:
                    current_doctrine[key] = value
            
            elif current_section == 'Arguments':
                if key == 'argument_id':
                    current_argument = {'argument_id': value}
                    kg.arguments.append(current_argument)
                    
                    # Create relationship with current case
                    if current_case and 'case_id' in current_case:
                        kg.case_arguments.append({
                            'case_id': current_case['case_id'],
                            'argument_id': value
                        })
                
                elif key in ['argument_text', 'argument_pattern'] and current_argument:
                    current_argument[key] = value
                
                elif key == 'submitted_by' and current_argument:
                    kg.argument_submitters.append({
                        'argument_id': current_argument['argument_id'],
                        'party_id': value
                    })
            
            elif current_section == 'Allegations':
                if key == 'allegation_id':
                    current_allegation = {'allegation_id': value}
                    kg.allegations.append(current_allegation)
                    
                    # Create relationship with current case
                    if current_case and 'case_id' in current_case:
                        kg.case_allegations.append({
                            'case_id': current_case['case_id'],
                            'allegation_id': value
                        })
                
                elif key in ['allegation_text', 'type'] and current_allegation:
                    current_allegation[key] = value
                
                elif key == 'alleges_against' and current_allegation:
                    targets = [target.strip() for target in value.split(',')]
                    for target in targets:
                        kg.allegation_targets.append({
                            'allegation_id': current_allegation['allegation_id'],
                            'target_id': target
                        })
            
            elif current_section == 'Ruling':
                if key == 'ruling_id':
                    current_ruling = {'ruling_id': value}
                    kg.rulings.append(current_ruling)
                    
                    # Create relationship with current case
                    if current_case and 'case_id' in current_case:
                        kg.case_rulings.append({
                            'case_id': current_case['case_id'],
                            'ruling_id': value
                        })
                
                elif key in ['ruling_date', 'vote_split', 'majority_author', 'majority_text', 'dissenting'] and current_ruling:
                    current_ruling[key] = value
            
            elif current_section == 'Relief':
                if key == 'relief_id':
                    current_relief = {'relief_id': value}
                    kg.reliefs.append(current_relief)
                    
                    # Create relationship with current case
                    if current_case and 'case_id' in current_case:
                        kg.case_reliefs.append({
                            'case_id': current_case['case_id'],
                            'relief_id': value
                        })
                
                elif key in ['relief_type', 'relief_description', 'legal_basis', 'enforcement_mechanisms'] and current_relief:
                    current_relief[key] = value
            
            elif current_section == 'Evidence':
                if key == 'document_id':
                    current_evidence = {'document_id': value}
                
                elif key in ['type', 'description'] and current_evidence:
                    current_evidence[key] = value
                
                elif key == 'case_id' and current_evidence:
                    kg.evidence.append({'document_id': current_evidence['document_id']})
                    kg.evidence_in_cases.append({
                        'document_id': current_evidence['document_id'],
                        'case_id': value,
                        'type': current_evidence.get('type', ''),
                        'description': current_evidence.get('description', '')
                    })
        
        # Flush the last case
        flush_case()
        
        # Add unique entities to knowledge graph
        kg.parties = list(parties_map.values())
        kg.provisions = list(provisions_map.values())
        kg.doctrines = list(doctrines_map.values())
        
        logger.info(f"Parsed knowledge graph with {len(kg.cases)} cases, {len(kg.parties)} parties, {len(kg.provisions)} provisions")
        
        return kg
    
    except Exception as e:
        logger.error(f"Error parsing document: {e}")
        raise Exception(f"Failed to parse document: {str(e)}")

def knowledge_graph_to_dict(kg: KnowledgeGraph) -> Dict[str, Any]:
    """Convert KnowledgeGraph object to dictionary for JSON serialization."""
    return {
        'cases': kg.cases,
        'parties': kg.parties,
        'provisions': kg.provisions,
        'doctrines': kg.doctrines,
        'arguments': kg.arguments,
        'allegations': kg.allegations,
        'rulings': kg.rulings,
        'reliefs': kg.reliefs,
        'evidence': kg.evidence,
        'caseParties': kg.case_parties,
        'caseProvisions': kg.case_provisions,
        'caseAllegations': kg.case_allegations,
        'allegationTargets': kg.allegation_targets,
        'caseArguments': kg.case_arguments,
        'argumentSubmitters': kg.argument_submitters,
        'argumentDoctrines': kg.argument_doctrines,
        'caseRulings': kg.case_rulings,
        'rulingDoctrines': kg.ruling_doctrines,
        'caseReliefs': kg.case_reliefs,
        'evidenceInCases': kg.evidence_in_cases
    } 