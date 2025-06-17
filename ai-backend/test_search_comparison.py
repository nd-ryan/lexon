#!/usr/bin/env python3
"""
Test file to compare manual Cypher query results with AI Agent search flow.
This test verifies that the AI Agent search correctly retrieves and formats doctrine data.

Test Query: "Can you get all the doctrines from the database"
"""

import asyncio
import json
import sys
import os
from typing import Dict, List, Any
from datetime import datetime

# Add the app directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.lib.neo4j_client import neo4j_client
from app.routes.ai import search_with_crew
from app.routes.ai import QueryRequest, StructuredSearchResponse

class SearchComparisonTest:
    def __init__(self):
        self.test_query = "Can you get all the doctrines from the database"
        self.manual_cypher = """
        MATCH (d:Doctrine)
        RETURN d.name as doctrine_name, 
               d.description as description,
               d.category as category,
               d.source as source,
               id(d) as doctrine_id,
               labels(d) as labels,
               properties(d) as all_properties
        ORDER BY d.name
        """
        self.results = {}
        
    def print_header(self, title: str):
        """Print a formatted header"""
        print("\n" + "="*80)
        print(f" {title}")
        print("="*80)
        
    def print_section(self, title: str):
        """Print a formatted section header"""
        print(f"\n{'-'*60}")
        print(f" {title}")
        print(f"{'-'*60}")
        
    async def run_manual_cypher_query(self) -> List[Dict[str, Any]]:
        """Execute the manual Cypher query to get all doctrines"""
        self.print_section("MANUAL CYPHER QUERY")
        print(f"Query: {self.manual_cypher.strip()}")
        
        try:
            # Execute the manual query
            results = neo4j_client.execute_query(self.manual_cypher)
            
            print(f"\nResults found: {len(results)}")
            
            # Display first few results for verification
            if results:
                print("\nFirst 3 results (preview):")
                for i, result in enumerate(results[:3]):
                    print(f"  {i+1}. {result.get('doctrine_name', 'N/A')}")
                    if result.get('description'):
                        print(f"     Description: {result.get('description', 'N/A')[:100]}...")
                    print(f"     Category: {result.get('category', 'N/A')}")
                    print()
            
            self.results['manual_query'] = {
                'cypher': self.manual_cypher.strip(),
                'results': results,
                'count': len(results),
                'execution_time': None  # Neo4j client doesn't return timing
            }
            
            return results
            
        except Exception as e:
            print(f"❌ Error executing manual query: {e}")
            self.results['manual_query'] = {
                'cypher': self.manual_cypher.strip(),
                'results': [],
                'count': 0,
                'error': str(e)
            }
            return []
    
    def run_ai_agent_search(self) -> StructuredSearchResponse:
        """Execute the AI Agent search flow"""
        self.print_section("AI AGENT SEARCH FLOW")
        print(f"Query: '{self.test_query}'")
        
        try:
            # Create request object
            request = QueryRequest(query=self.test_query)
            
            # Execute the AI Agent search
            print("\nExecuting AI Agent search...")
            ai_result = search_with_crew(request)
            
            print(f"✅ AI search completed successfully")
            print(f"Success: {ai_result.success}")
            print(f"Total results: {ai_result.total_results}")
            print(f"Execution time: {ai_result.execution_time:.2f}s" if ai_result.execution_time else "N/A")
            print(f"MCP tools used: {ai_result.mcp_tools_used}")
            
            # Display analysis summary
            if ai_result.analysis:
                print(f"\nQuery interpretation: {ai_result.analysis.query_interpretation}")
                print(f"Methodology steps: {len(ai_result.analysis.methodology)}")
                print(f"Key insights: {len(ai_result.analysis.key_insights)}")
                print(f"Formatted results: {len(ai_result.analysis.formatted_results)}")
                print(f"Raw query results: {len(ai_result.analysis.raw_query_results)}")
            
            self.results['ai_search'] = ai_result
            return ai_result
            
        except Exception as e:
            print(f"❌ Error executing AI search: {e}")
            # Create a mock failed response
            from app.routes.ai import SearchAnalysis
            failed_response = StructuredSearchResponse(
                success=False,
                query=self.test_query,
                total_results=0,
                results=[],
                cypher_queries=[],
                analysis=SearchAnalysis(
                    query_interpretation=f"Failed to process: {self.test_query}",
                    methodology=["Attempted AI Agent search"],
                    key_insights=[f"Error: {str(e)}"],
                    patterns_identified=[],
                    limitations=["Search execution failed"],
                    formatted_results=[],
                    raw_query_results=[]
                ),
                execution_time=0.0,
                mcp_tools_used=False,
                agent_reasoning=[]
            )
            self.results['ai_search'] = failed_response
            return failed_response
    
    def compare_results(self):
        """Compare the manual query results with AI Agent search results"""
        self.print_section("RESULTS COMPARISON")
        
        manual_results = self.results.get('manual_query', {})
        ai_results = self.results.get('ai_search')
        
        if not manual_results.get('results') and not ai_results:
            print("❌ No results to compare - both queries failed")
            return
        
        # Basic comparison
        manual_count = manual_results.get('count', 0)
        ai_count = ai_results.total_results if ai_results else 0
        
        print(f"Manual query count: {manual_count}")
        print(f"AI search count: {ai_count}")
        
        if manual_count == ai_count and manual_count > 0:
            print("✅ Result counts match!")
        elif manual_count > 0 and ai_count > 0:
            print("⚠️  Result counts differ - may indicate different query approaches")
        else:
            print("❌ One or both queries returned no results")
        
        # Compare actual data if available
        if manual_results.get('results') and ai_results and ai_results.analysis.raw_query_results:
            self.compare_data_content(manual_results['results'], ai_results.analysis.raw_query_results)
        
        # Analyze AI search quality
        if ai_results and ai_results.success:
            self.analyze_ai_search_quality(ai_results)
    
    def compare_data_content(self, manual_data: List[Dict], ai_data: List[Dict]):
        """Compare the actual data content between manual and AI results"""
        print(f"\n📊 Data Content Comparison:")
        
        # Extract doctrine names for comparison
        manual_doctrines = set()
        for item in manual_data:
            if 'doctrine_name' in item and item['doctrine_name']:
                manual_doctrines.add(item['doctrine_name'].lower().strip())
        
        ai_doctrines = set()
        for item in ai_data:
            # Try different possible field names
            for field in ['doctrine_name', 'name', 'd.name', 'title']:
                if field in item and item[field]:
                    ai_doctrines.add(str(item[field]).lower().strip())
                    break
        
        print(f"Manual query unique doctrines: {len(manual_doctrines)}")
        print(f"AI search unique doctrines: {len(ai_doctrines)}")
        
        # Find overlaps and differences
        common = manual_doctrines.intersection(ai_doctrines)
        manual_only = manual_doctrines - ai_doctrines
        ai_only = ai_doctrines - manual_doctrines
        
        print(f"Common doctrines: {len(common)}")
        print(f"Only in manual: {len(manual_only)}")
        print(f"Only in AI: {len(ai_only)}")
        
        if common:
            print(f"\n✅ Sample common doctrines: {list(common)[:5]}")
        
        if manual_only:
            print(f"\n⚠️  Doctrines only in manual query: {list(manual_only)[:5]}")
        
        if ai_only:
            print(f"\n⚠️  Doctrines only in AI search: {list(ai_only)[:5]}")
    
    def analyze_ai_search_quality(self, ai_result: StructuredSearchResponse):
        """Analyze the quality and completeness of the AI search"""
        print(f"\n🤖 AI Search Quality Analysis:")
        
        analysis = ai_result.analysis
        
        # Check if methodology mentions doctrines
        methodology_mentions_doctrines = any(
            'doctrine' in step.lower() for step in analysis.methodology
        )
        print(f"Methodology mentions doctrines: {methodology_mentions_doctrines}")
        
        # Check if formatted results contain doctrine information
        formatted_has_doctrines = any(
            'doctrine' in result.lower() for result in analysis.formatted_results
        )
        print(f"Formatted results contain doctrine info: {formatted_has_doctrines}")
        
        # Check query interpretation
        interpretation_relevant = 'doctrine' in analysis.query_interpretation.lower()
        print(f"Query interpretation mentions doctrines: {interpretation_relevant}")
        
        # Overall quality score
        quality_score = sum([
            ai_result.success,
            ai_result.mcp_tools_used,
            methodology_mentions_doctrines,
            formatted_has_doctrines,
            interpretation_relevant,
            len(analysis.raw_query_results) > 0
        ])
        
        print(f"\n📈 Overall quality score: {quality_score}/6")
        
        if quality_score >= 5:
            print("✅ Excellent AI search quality")
        elif quality_score >= 3:
            print("⚠️  Good AI search quality with room for improvement")
        else:
            print("❌ Poor AI search quality - needs investigation")
    
    def save_detailed_results(self):
        """Save detailed results to a JSON file for further analysis"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"search_comparison_results_{timestamp}.json"
        
        # Prepare data for JSON serialization
        export_data = {
            'test_info': {
                'query': self.test_query,
                'timestamp': timestamp,
                'manual_cypher': self.manual_cypher.strip()
            },
            'manual_query': self.results.get('manual_query', {}),
            'ai_search': {}
        }
        
        # Convert AI search results to JSON-serializable format
        if 'ai_search' in self.results:
            ai_result = self.results['ai_search']
            export_data['ai_search'] = {
                'success': ai_result.success,
                'query': ai_result.query,
                'total_results': ai_result.total_results,
                'execution_time': ai_result.execution_time,
                'mcp_tools_used': ai_result.mcp_tools_used,
                'cypher_queries': ai_result.cypher_queries,
                'analysis': {
                    'query_interpretation': ai_result.analysis.query_interpretation,
                    'methodology': ai_result.analysis.methodology,
                    'key_insights': ai_result.analysis.key_insights,
                    'patterns_identified': ai_result.analysis.patterns_identified,
                    'limitations': ai_result.analysis.limitations,
                    'formatted_results': ai_result.analysis.formatted_results,
                    'raw_query_results': ai_result.analysis.raw_query_results
                }
            }
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)
            print(f"\n💾 Detailed results saved to: {filename}")
        except Exception as e:
            print(f"❌ Error saving results: {e}")
    
    async def run_full_test(self):
        """Run the complete comparison test"""
        self.print_header("SEARCH COMPARISON TEST")
        print(f"Test Query: '{self.test_query}'")
        print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # Step 1: Run manual Cypher query
            await self.run_manual_cypher_query()
            
            # Step 2: Run AI Agent search
            self.run_ai_agent_search()
            
            # Step 3: Compare results
            self.compare_results()
            
            # Step 4: Save detailed results
            self.save_detailed_results()
            
            self.print_header("TEST COMPLETED")
            print("✅ Search comparison test completed successfully!")
            
        except Exception as e:
            print(f"\n❌ Test failed with error: {e}")
            import traceback
            traceback.print_exc()

async def main():
    """Main function to run the test"""
    print("🧪 Starting Search Comparison Test...")
    
    # Check if Neo4j connection is available
    try:
        # Simple connection test
        test_query = "MATCH (n) RETURN count(n) as total_nodes LIMIT 1"
        result = neo4j_client.execute_query(test_query)
        print(f"✅ Neo4j connection successful. Total nodes: {result[0]['total_nodes'] if result else 'Unknown'}")
    except Exception as e:
        print(f"❌ Neo4j connection failed: {e}")
        print("Please ensure Neo4j is running and accessible.")
        return
    
    # Run the test
    test = SearchComparisonTest()
    await test.run_full_test()

if __name__ == "__main__":
    asyncio.run(main()) 