from copy import deepcopy
from typing import List

import numpy as np
from pymatgen.core.sites import PeriodicSite
from pymatgen.core.structure import Structure, Molecule

from ocelot.routines.pbc import PBCparser
from ocelot.schema.conformer import ConformerDimer, MolConformer, conformer_addhmol


class Config:
    zreal: int
    unwrap_structure: Structure
    mols: List[Molecule]
    pstructure: Structure

    def __init__(self, pstructure):
        """
        :param pstructure: Structure without disorder
        """
        self.pstructure = pstructure
        self.mols, self.molconformers, self.unwrap_structure = PBCparser.squeeze(self.pstructure)
        self.zreal = len(self.mols)
        self.z = len([omol for omol in self.molconformers if not omol.is_solvent])  # no solvent!
        if self.z < self.zreal:
            self.hassolvent = True
        else:
            self.hassolvent = False
        for i in range(self.z):
            self.molconformers[i].conformer_properties = {'index in the cell': i}
        # self.dimers_array, self.transv_fcs = self.get_dimers_array(2)

    def as_dict(self, dimermaxfold=2):
        """
        keys are

        pymatgen_structure, mols, omols, z, dimers_dict_array
        """
        d = {"@module": self.__class__.__module__, "@class": self.__class__.__name__,
             'pymatgen_structure': self.pstructure.as_dict(), 'mols': [m.as_dict() for m in self.mols],
             'mcs': [m.as_dict() for m in self.molconformers], 'z': self.z}

        dimers_array, transv_fcs = self.get_dimers_array(dimermaxfold)
        dimers_dictarray = np.empty((self.z, self.z, len(transv_fcs)), dtype=dict)
        for i in range(self.z):
            for j in range(self.z):
                for k in range(len(transv_fcs)):
                    dimers_dictarray[i][j][k] = dimers_array[i][j][k].as_dict()
        d['dimers_dict_array'] = dimers_dictarray
        return d

    @classmethod
    def from_dict(cls, d):
        """
        keys are

        pymatgen_structure
        """
        pstructure = Structure.from_dict(d['pymatgen_structure'])
        return cls(pstructure)

    def get_dimers_array(self, maxfold=2, fast=False, symm=False):
        """
        :param fast:
        :param symm:
        :param maxfold: translation vector in fc can be [h, h, h] where maxfold <= h <= maxfold
        :return: dimers_array, z x z x n array, dimers[i][j][k] is the dimer of omols[i], omols[j] with translation vector as transv_fcs[k]
                 transv_fcs
        """
        transv_1d = list(range(-maxfold, maxfold + 1))
        transv_fcs = np.array(np.meshgrid(transv_1d, transv_1d, transv_1d)).T.reshape(-1, 3)
        # symmetry dimers[i][j][transv_fcs[k]] = dimers[j][i][-transv_fcs[k]]
        nuni = int((len(transv_fcs) + 1) / 2)
        uni_transv_fcs = transv_fcs[:nuni]  # as transv_fcs[i] == -transv_fcs[len-i-1]
        if symm:
            dimers = np.empty((self.z, self.z, len(uni_transv_fcs)), dtype=ConformerDimer)
            used_transv_fcs = uni_transv_fcs
        else:
            dimers = np.empty((self.z, self.z, len(transv_fcs)), dtype=ConformerDimer)
            used_transv_fcs = transv_fcs

        for i in range(self.z):
            ref_omol = self.molconformers[i]
            for j in range(self.z):
                var_omol = self.molconformers[j]
                for k in range(len(used_transv_fcs)):
                    transv = self.unwrap_structure.lattice.get_cartesian_coords(used_transv_fcs[k])
                    if fast:
                        var_omol_k = deepcopy(var_omol)
                        for h in range(len(var_omol_k)):
                            var_omol_k.sites[h].coords += transv
                        dimer_ijk = ConformerDimer(ref_omol, var_omol_k, label="{}_{}_{}".format(i, j, k))
                        # dimer_ji_nk = Dimer(ref_omol, var_omol_nk, label="{}-{}_{}".format(i, j, ntrans-k-1))
                    else:
                        msites = deepcopy(var_omol.sites)
                        for h in range(len(msites)):
                            msites[h].coords += transv
                        dimer_ijk = ConformerDimer(ref_omol, MolConformer(msites, prop=var_omol.conformer_properties),
                                                   label="{}_{}_{}".format(i, j, k))
                    dimers[i][j][k] = dimer_ijk
        return dimers, transv_fcs

    def get_bone_config(self):
        """
        :return:
            a configuration that has only terminated backbones
            a pmg structure that has only terminated backbones
            a list of pmg molecules
        """

        terminated_backbone_hmols = [
            conformer_addhmol(mc.backbone, joints=mc.backbone_graph.joints, original=mc) for mc in
            self.molconformers]

        backbone_sites = []
        for b in terminated_backbone_hmols:
            backbone_sites += b.sites

        boneonly_psites = [PeriodicSite(s.species_string, s.coords, self.unwrap_structure.lattice, to_unit_cell=True,
                                        coords_are_cartesian=True)
                           for s in backbone_sites]
        boneonly_pstructure = Structure.from_sites(boneonly_psites)
        return Config(boneonly_pstructure), boneonly_pstructure, terminated_backbone_hmols

    @classmethod
    def from_cifstring(cls, string):
        s = Structure.from_str(string, fmt='cif')
        return cls(s)

    @classmethod
    def from_file(cls, filename):
        s = Structure.from_file(filename)
        return cls(s)