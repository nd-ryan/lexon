import { extractRawText } from 'mammoth';

export interface KG {
  cases: CaseNode[];
  parties: PartyNode[];
  provisions: ProvisionNode[];
  doctrines: DoctrineNode[];
  arguments: ArgumentNode[];
  allegations: AllegationNode[];
  rulings: RulingNode[];
  reliefs: ReliefNode[];
  evidence: EvidenceNode[];

  caseParties:    HasPartyRel[];
  caseProvisions: CitesProvRel[];
  caseAlleg:      IncludesAllegRel[];
  allegTargets:   AllegesAgainstRel[];
  caseArgs:       HasArgRel[];
  argSubmit:      SubmittedByRel[];
  argDoctrine:    SupportsDocRel[];
  caseRuling:     HasRulingRel[];
  rulingDoctrine: AppliesDocRel[];
  caseRelief:     HasReliefRel[];
  evidIn:         EvidenceInRel[];
}

// --- Node Interfaces ---
export interface CaseNode { case_id: string; [key: string]: any; }
export interface PartyNode { party_id: string; [key: string]: any; }
export interface ProvisionNode { provision_id: string; [key: string]: any; }
export interface DoctrineNode { doctrine_id: string; [key: string]: any; }
export interface ArgumentNode { argument_id: string; [key: string]: any; }
export interface AllegationNode { allegation_id: string; [key: string]: any; }
export interface RulingNode { ruling_id: string; [key: string]: any; }
export interface ReliefNode { relief_id: string; [key: string]: any; }
export interface EvidenceNode { document_id: string; }

// --- Relationship Interfaces ---
export interface HasPartyRel { case_id: string; party_id: string; role: string | null; }
export interface CitesProvRel { case_id: string; provision_id: string; }
export interface IncludesAllegRel { case_id: string; allegation_id: string; }
export interface AllegesAgainstRel { allegation_id: string; target_id: string; }
export interface HasArgRel { case_id: string; argument_id: string; }
export interface SubmittedByRel { argument_id: string; party_id: string; }
export interface SupportsDocRel { argument_id: string; doctrine_id: string; }
export interface HasRulingRel { case_id: string; ruling_id: string; }
export interface AppliesDocRel { ruling_id: string; doctrine_id: string; }
export interface HasReliefRel { case_id: string; relief_id: string; }
export interface EvidenceInRel { document_id: string; case_id: string; type: string; description: string; }

const SECTIONS = [
  'Case', 'Parties', 'Legal Provisions',
  'Legal Doctrines', 'Arguments', 'Allegations',
  'Ruling', 'Relief', 'Evidence'
] as const;
type SectionType = typeof SECTIONS[number];

export async function parseDocx(buffer: Buffer): Promise<KG> {
  const raw = (await extractRawText({ buffer })).value
    .split('\n').map(l => l.trim()).filter(Boolean);

  const kg: KG = { 
    cases: [], parties: [], provisions: [], doctrines: [], arguments: [], 
    allegations: [], rulings: [], reliefs: [], evidence: [],
    caseParties: [], caseProvisions: [], caseAlleg: [], allegTargets: [],
    caseArgs: [], argSubmit: [], argDoctrine: [], caseRuling: [],
    rulingDoctrine: [], caseRelief: [], evidIn: []
  };

  const partiesMap = new Map<string, PartyNode>(), 
        provMap = new Map<string, ProvisionNode>(),
        doctrineMap = new Map<string, DoctrineNode>();

  let section: SectionType | null = null, 
      curCase: any = null, curParty: any = null, curProv: any = null,
      curDoc: any = null, curArg: any = null, curAlleg: any = null,
      curRuling: any = null, curRelief: any = null, curEv: any = null;

  const flushCase = () => { if (curCase) kg.cases.push(curCase); };

  for (const line of raw) {
    if (line.startsWith('🔸 Case:')) { flushCase(); curCase = {}; section = null; continue; }
    if ((SECTIONS as readonly string[]).includes(line)) { section = line as SectionType; continue; }
    if (!section || !line.includes(':')) continue;
    
    const [key, rawVal] = line.split(':', 2); 
    const val = rawVal.trim();

    if (section === 'Case') curCase[key.trim()] = val;
    else if (section === 'Parties')   {                // ----- Parties -----
      if (key === 'party_id') {
        const pid = val.match(/\d+/)?.[0] ?? val;
        curParty = partiesMap.get(pid) ?? { party_id: pid };
        partiesMap.set(pid, curParty);
        if (curCase.case_id) kg.caseParties.push({ case_id: curCase.case_id,
                                                   party_id: pid, role: null });
      } else if (['party_name','party_type'].includes(key))  curParty[key] = val;
      else if (key === 'role') {
        const rel = kg.caseParties.find(r => r.case_id === curCase.case_id && r.party_id === curParty.party_id);
        if (rel) rel.role = val;
      }
    }
    else if (section === 'Legal Provisions') {        // ----- Provisions -----
      if (key === 'provision_id') {
        const vid = val.match(/\d+/)?.[0] ?? val;
        curProv = provMap.get(vid) ?? { provision_id: vid };
        provMap.set(vid, curProv);
        if (curCase.case_id) kg.caseProvisions.push({ case_id: curCase.case_id, provision_id: vid });
      } else if (['provision_name','provision_statute','provision_text'].includes(key)) curProv[key] = val;
    }
    else if (section === 'Legal Doctrines') {
      if (key === 'doctrine_id') {
        const did = val.match(/\w+/)?.[0] ?? val;
        curDoc = doctrineMap.get(did) ?? { doctrine_id: did };
        doctrineMap.set(did, curDoc);
        if (curArg?.argument_id) kg.argDoctrine.push({ argument_id: curArg.argument_id, doctrine_id: did });
        if (curRuling?.ruling_id) kg.rulingDoctrine.push({ ruling_id: curRuling.ruling_id, doctrine_id: did });
      } else if (key === 'doctrine_name' || key === 'description') {
        curDoc[key] = val;
      }
    } else if (section === 'Arguments') {
      if (key === 'argument_id') {
        curArg = { argument_id: val };
        kg.arguments.push(curArg);
        if (curCase.case_id) kg.caseArgs.push({ case_id: curCase.case_id, argument_id: val });
      } else if (key === 'argument_text' || key === 'argument_pattern') {
        curArg[key] = val;
      } else if (key === 'submitted_by') {
        kg.argSubmit.push({ argument_id: curArg.argument_id, party_id: val });
      }
    } else if (section === 'Allegations') {
      if (key === 'allegation_id') {
        curAlleg = { allegation_id: val };
        kg.allegations.push(curAlleg);
        if (curCase.case_id) kg.caseAlleg.push({ case_id: curCase.case_id, allegation_id: val });
      } else if (key === 'allegation_text' || key === 'type') {
        curAlleg[key] = val;
      } else if (key === 'alleges_against') {
        val.split(',').forEach(target => {
          kg.allegTargets.push({ allegation_id: curAlleg.allegation_id, target_id: target.trim() });
        });
      }
    } else if (section === 'Ruling') {
      if (key === 'ruling_id') {
        curRuling = { ruling_id: val };
        kg.rulings.push(curRuling);
        if (curCase.case_id) kg.caseRuling.push({ case_id: curCase.case_id, ruling_id: val });
      } else if (['ruling_date','vote_split','majority_author','majority_text','dissenting'].includes(key)) {
        curRuling[key] = val;
      }
    } else if (section === 'Relief') {
      if (key === 'relief_id') {
        curRelief = { relief_id: val };
        kg.reliefs.push(curRelief);
        if (curCase.case_id) kg.caseRelief.push({ case_id: curCase.case_id, relief_id: val });
      } else if (['relief_type','relief_description','legal_basis','enforcement_mechanisms'].includes(key)) {
        curRelief[key] = val;
      }
    } else if (section === 'Evidence') {
      if (key === 'document_id') {
        curEv = { document_id: val };
      } else if (key === 'type' || key === 'description') {
        curEv[key] = val;
      } else if (key === 'case_id') {
        kg.evidence.push({ document_id: curEv.document_id });
        kg.evidIn.push({
          document_id: curEv.document_id,
          case_id: val,
          type: curEv.type,
          description: curEv.description,
        });
      }
    }
  }
  flushCase();
  kg.parties    = [...partiesMap.values()];
  kg.provisions = [...provMap.values()];
  kg.doctrines  = [...doctrineMap.values()];
  return kg;
} 