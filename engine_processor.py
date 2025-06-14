#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Powered by Renoir
Author: Igor Daniel G Goncalves - igor.goncalves@renoirgroup.com

Formula Pre-Processor Module
----------------------------

This module is responsible for processing hierarchical formulas and extracting variables
from a tree-structured data source. It performs several key operations:

1. Loading tree data from a JSON file (tree_data.json)
2. Extracting and parsing formulas using the engine_parser module
3. Processing variables by analyzing the tree structure and applying filters
4. Saving the processed results to output JSON files

The module handles both simple variable references and complex aggregation functions,
supporting both global and ID-specific contexts. It processes each formula for each ID
in the tree, extracting relevant variable values according to the formula's structure.

Example workflow:
1. Load the tree data from JSON
2. Extract and parse formulas using the parser
3. Process each formula group for each ID
4. For each formula, extract variables both with and without aggregation
5. Save the processed results to the output file

This module is typically used as part of a larger hierarchical formula evaluation system.

Dependencies:
- filters.filters_paths: For filtering tree data based on paths and expressions
- engine_parser: For parsing formula syntax
- log.logger: For logging events and errors
"""
import json
import copy
import engine_entities, engine_parser, engine_eval, update_frappe, update_tree
import engine_entities.engine_data, engine_entities.get_doctypes, engine_parser 
from typing import Dict, List, Any
from filters.filters_paths import filter_tree_data
from log.logger import get_logger
from variable_filter import FilterVariableExtractor
from engine_logger import EngineLogger

class EngineProcessor(EngineLogger):

    def __init__(self):
        self.logger = get_logger("Engine - Processor")

    def enrich_formulas_with_values(self, extracted_formulas: List[Dict[str, Any]], tree_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process extracted formulas and enrich them with variable values for each ID.
        
        This function is the core of the formula pre-processing. It takes the parsed formulas
        and for each formula and ID combination:
        1. Extracts simple variable references directly from the tree
        2. Processes aggregation functions, handling both global and local (ID-specific) contexts
        3. Combines the results into a structured output format
        
        The function handles two types of variable extraction:
        - Non-aggregated variables: Simple direct variable references
        - Aggregated variables: Variables used within aggregation functions (sum, avg, etc.)
        with optional filters and global/local scope
        
        Args:
            extracted_formulas: List of formula groups, each containing formulas and associated IDs
                            (output from the parse_formulas function)
            tree_data: The complete tree data structure (loaded from JSON)
            
        Returns:
            List of dictionaries containing processed formulas with their variable values
            for each ID. The structure includes entity, ID, and formula data with extracted
            variable values.
            
        Raises:
            Exception: For errors in variable extraction or tree data filtering
        """

        self.log_info(f"Starting to process formula variables for {len(extracted_formulas)} formula groups")
        
        group_result = []
    
        for i, formula_group in enumerate(extracted_formulas):
            self.log_debug(f"Processing formula group {i+1}/{len(extracted_formulas)}: {formula_group.get('path', 'unknown')}")
            
            # Process each ID in the group
            for id_obj in formula_group.get("ids", []):
                id_value = id_obj["id"]
                self.log_debug(f"Processing ID: {id_value}")
                
                formula_ids = {}

                # For each formula, extract variable values
                for formula in formula_group["formulas"]:
                    formula_path = formula["path"]
                    formula_value = formula['value']
                    self.log_debug(f"Processing formula: {formula_path}: {formula_value} for ID: {id_value}")

                    # Create a new entry for this formula path if it doesn't exist
                    formula_ids.setdefault(formula["path"], [])

                    # Process non-aggregated variables
                    # These are direct variable references without aggregation functions
                    vars = formula.get("parsed", []).get("vars", [])
                    self.log_debug(f"Extracting non-aggregated variables: {vars}")
                    try:
                        # Apply "first" transformation to get only the first match for each variable
                        node = filter_tree_data(tree_data, [f"first({v})" for v in vars], id_value)
                        self.log_debug(f"Found {len(node)} non-aggregated variable nodes")
                        for n in node:
                            formula_ids[formula["path"]].append({"non_aggr": n})
                    except Exception as e:
                        self.log_error(f"Error processing non-aggregated variables: {e}")
                        raise

                    # Process aggregation functions (sum, avg, etc.)
                    aggr_funcs = formula.get("parsed", []).get("aggr", [])
                    self.log_debug(f"Processing {len(aggr_funcs)} aggregation functions")
                    
                    for aggr in aggr_funcs:

                        vars = aggr["vars"]
                        filter_expr = aggr["filter"]
                        is_global = aggr["global"]

                        filter_aggr_expr = []

                        # Check if exits var fields in right side of filter expression
                        if filter_expr:
                            # Extract unique variables from the filter expression
                            filter_vars = FilterVariableExtractor().extract_unique_variables(filter_expr)
                            # If there are variables in the filter expression, we need to process them
                            if filter_vars:
                                self.log_debug(f"Filter expression found: {filter_expr}")
                                # Highlight variables in the filter expression
                                new_filter_expr = FilterVariableExtractor().highlight_variables(filter_expr)
                                self.log_debug(f"Get values for right variables: {filter_vars}")
                                try:
                                    # Apply "first" transformation to get only the first match for each variable
                                    for v in filter_vars:
                                        # Set function to get the first value of the variable
                                        var_list = [f"first({v})"]
                                        self.log_debug(f"Searching for variable: {v} in tree data")
                                        # Search for the variable in the tree data
                                        node = filter_tree_data(tree_data, return_paths=var_list, record_id=id_value, lock_node=True)
                                        if node:
                                            n_value = node[0]["values"][0]
                                            # Append the variable value to the filter aggregation expression
                                            filter_aggr_expr.append({v:n_value})
                                            self.log_debug(f"Found variable value {n_value}")
                                            try:
                                                # Check if the value is a number
                                                float(n_value)
                                            except (ValueError, TypeError):
                                                # Enclose in quotes if not a number
                                                n_value = f"'{n_value}'"  
                                            # Replace the variable in the filter expression
                                            new_filter_expr = new_filter_expr.replace(f"__{v}__", n_value)
                                except Exception as e:
                                    self.log_error(f"Error processing non-aggregated variables: {e}")
                                    raise
                                self.log_debug(f"Updated filter expression: {new_filter_expr}")
                                # Change the filter expression to the new one with values
                                filter_expr = new_filter_expr
                        
                        self.log_debug(f"Processing aggregation function - vars: {vars}, filter: {filter_expr}, global: {is_global}")

                        # Search for the variable in the tree data
                        # Global aggregations search across the entire tree
                        if is_global:
                            self.log_debug("Processing global aggregation")
                            try:
                                if filter_expr:
                                    self.log_debug(f"Applying global filter: {filter_expr}")
                                    # For variables in aggregation functions with filter
                                    # Global filter ignores the ID
                                    node = filter_tree_data(tree_data, vars, filter_expr=filter_expr)
                                else:
                                    self.log_debug("No filter applied, getting all values")
                                    # If no filter, just get all values
                                    node = filter_tree_data(tree_data, vars)
                                self.log_debug(f"Found {len(node)} nodes for global aggregation")
                                # Append all values to the formula_ids
                                for n in node:
                                    formula_ids[formula["path"]].append({"aggr": {"base": aggr["base"], "vars": n, "filter": filter_aggr_expr}})
                                # If no nodes found
                                if not node:
                                    formula_ids[formula["path"]].append({"aggr": {"base": aggr["base"], "vars": [], "filter": filter_aggr_expr}})
                            except Exception as e:
                                self.log_error(f"Error processing global aggregation: {e}")
                                raise

                        # Local aggregations only search within the current ID and its subnodes
                        else:
                            self.log_debug("Processing local aggregation (ID-specific)")
                            try:
                                if filter_expr:
                                    self.log_debug(f"Applying local filter with ID {id_value}: {filter_expr}")
                                    # For variables in aggregation functions with filter
                                    node = filter_tree_data(tree_data, vars, id_value, filter_expr, lock_node=True)
                                else:
                                    self.log_debug(f"No filter applied, getting all values for ID {id_value}")
                                    # If no filter, just get all values
                                    node = filter_tree_data(tree_data, vars, id_value, lock_node=True)
                                self.log_debug(f"Found {len(node)} nodes for local aggregation")
                                for n in node:  
                                    formula_ids[formula["path"]].append({"aggr": aggr["base"], "vars": n, "filter": filter_aggr_expr})
                                # If no nodes found
                                if not node:
                                    formula_ids[formula["path"]].append({"aggr": {"base": aggr["base"], "vars": [], "filter": filter_aggr_expr}})
                            except Exception as e:
                                self.log_error(f"Error processing local aggregation: {e}")
                                raise

                # Temporarily store the results for this ID
                self.log_debug(f"Creating result for ID {id_value} with {len(formula_ids)} formulas")
                id_result = {
                    "formulas": []
                }
                for key, value in formula_ids.items():
                    id_result["formulas"].append({"formula": key, "data": copy.deepcopy(value)})

                # Add this ID's results to the group
                group_item = {
                    "entity": formula_group["path"],
                    "id": id_value,
                    "formula_data": copy.deepcopy(id_result)
                }
                group_result.append(group_item)
                self.log_debug(f"Added result for entity {formula_group['path']}, ID {id_value}")
        
        self.log_info(f"Formula variable processing complete. Processed {len(group_result)} ID results")
        return group_result

    def calculate_measurements(self):
        """
        Main function to orchestrate the formula pre-processing workflow.
        
        This function serves as the entry point for the formula pre-processing module,
        orchestrating the entire workflow:
        
        1. Load tree data from the JSON file
        2. Extract and parse formulas from the tree data
        3. Process formula variables for each formula and ID
        4. Save the results to the output JSON file
        
        The function handles errors at each step, logging them appropriately and
        preventing further processing if a critical error occurs.
        
        Returns:
            None
        """
        self.log_info("Starting formula pre-processing")

        # Engine processor
        entities_processor = engine_entities.get_doctypes.DoctypeProcessor()

        # Get contract keys
        contract_keys = entities_processor.get_contracts()

        # Get formulas
        formulas = entities_processor.get_formula_data(using_cached_data=False)

        # Load and calculate tree data for each contract
        #for k in contract_keys:
        for k in ['0196b01a-2163-7cb2-93b9-c8b1342e3a4e']:

            self.log_info("=" * 80)
            self.log_info(f"Processing contract: {k}\n\n")
            self.log_info("=" * 80)
            
            # Get contract data
            contract_data = entities_processor.get_data(k)

            # Get contract formula group 
            find_contract = [item for item in contract_data['data'] if 'Contract' in item]

            # Check if contract data is found
            if not find_contract:
                self.log_error(f"No contract data found for {k}. Skipping.")
                continue

            # Extract contract formula IDs
            contract_formula_id = None
            try:                
                if find_contract[0]:
                    if find_contract[0]['Contract']:
                        if find_contract[0]['Contract'][0]:
                            if find_contract[0]['Contract'][0]['grupoformulas']:
                                contract_formula_id = find_contract[0]['Contract'][0]['grupoformulas'] if 'grupoformulas' in find_contract[0]['Contract'][0] else []
            except Exception as e:
                self.log_error(f"Error extracting contract formula IDs for {k}: {e}")
                continue

            if not contract_formula_id:
                self.log_error(f"No formula group IDs found for contract {k}. Skipping.")
                continue   

            # Filter formulas based on group
            contract_formula = [f for f in formulas if f.get("name") in contract_formula_id]  

            # Build engine data
            data_builder = engine_entities.engine_data.EngineDataBuilder(
                contract_data['hierarchical'], 
                contract_formula, 
                contract_data['data'], 
                "data",
                compact_mode=True
            )
            #Create data tree for the contract
            engine_data_tree = data_builder.build()

            with open(f"data_tree_{k}.json", 'w', encoding='utf-8') as f:
                json.dump(engine_data_tree, f, indent=4, ensure_ascii=False)        

            # Parse formulas
            parser = engine_parser.FormulaParser()
            extract_formulas = parser.parse_formulas(engine_data_tree)
            # Save the parsed formulas to a file
            with open(f"extract_formulas_{k}.json", 'w', encoding='utf-8') as f:
                json.dump(extract_formulas, f, indent=4, ensure_ascii=False)        

            # *******************************
            # *******************************
            # Executar for nos grupos de parsed formulas
            # *******************************
            # *******************************

            # # Extract and parse formulas
            # extracted_formulas = parse_formulas(engine_data_tree)
            # self.log_info(f"Successfully extracted {len(extracted_formulas)} formula groups")
            
            # Process formula variables
            enrich_formulas = self.enrich_formulas_with_values(extract_formulas, engine_data_tree)
            # Save processed formulas to a file
            with open(f"enrich_formulas_{k}.json", 'w', encoding='utf-8') as f:
                json.dump(enrich_formulas, f, indent=4, ensure_ascii=False) 

            engine = engine_eval.EngineEval()

            self.log_info("Starting formula evaluation")

            engine_results = engine.eval_formula(enrich_formulas, extract_formulas, engine_data_tree)
                
            # Print summary of results
            success_count = sum(1 for entity in engine_results for fr in entity["results"] if fr["status"] == "success")
            error_count = sum(1 for entity in engine_results for fr in entity["results"] if fr["status"] == "error")
            engine.log_info(f"Formula evaluation complete. Successful: {success_count}, Errors: {error_count}")

            # Convert numpy types to native Python types before saving
            engine_results_converted = engine.convert_numpy_types(engine_results)            

            # Write the results to a JSON file
            with open("engine_result.json", 'w', encoding='utf-8') as f:
                json.dump(engine_results_converted, f, indent=4, ensure_ascii=False)

            # Select the first formula to update
            for to_update_formula in extract_formulas:

                # Update tree_data and database
                utree = update_tree.UpdateTreeData(
                    engine_data_tree, 
                    to_update_formula, 
                    engine_results_converted
                )
                engine_data_tree = utree.update_tree()      

                # Save data to Frappe
                ufrappe = update_frappe.UpdateFrappe(engine_results_converted, to_update_formula)
                ufrappe.update()          

        
if __name__ == "__main__":
    processor = EngineProcessor()
    try:
        processor.calculate_measurements()
    except Exception as e:
        processor.log_error(f"An error occurred during formula processing: {e}")
        raise
    finally:
        processor.log_info("Formula processing completed.")