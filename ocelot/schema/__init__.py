"""
this contains the schema for dealing with conjugate organics, molecules and beyond

Graph:
    atom index: nodename

Molecule:
    RdMol
    format: smiles, smarts, inchi
    atom index: atomidx

Conformer:
    Dimer --> OrganicMolecule, Backbone, SideGroup, Ring --> BasicConformer
    format: xyz
    atom index: siteid

Configuration:
    SuperCell --> UnitCell --> AsymmUnit --> Configuration
    format: cif, poscar
    atom index: siteid

graph <--> molecule <--> conformer <--> configuration


#TODO Granular Schema
"""
