import os
import re
import subprocess
import warnings

import numpy as np
from pymatgen.core.structure import Element, Molecule, Site

from ocelot.routines.fileop import movefile

# http://www.esi.umontreal.ca/accelrys/life/insight2000.1/zindo/3_Implementation.html
Zindo_elements = [
    'H', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'K',
    'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Se', 'Br', 'Y', 'Zr',
    'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd'
]


def conver2zindo(pmgmol):
    """
    this will replace elements that are not in Zindo_elements with elements in the same group
    """
    if pmgmol is None:
        return None
    sites = pmgmol.sites
    newsites = []
    for s in sites:
        if not s.species_string in Zindo_elements:
            group = Element(s.species_string).group
            samegroup_symbols = [symbol for symbol in Zindo_elements if Element(symbol).group == group]
            replacement = sorted(samegroup_symbols, key=lambda x: Element(x).number, reverse=True)[0]
            newsites.append(Site(replacement, s.coords))
        else:
            newsites.append(Site(s.species_string, s.coords))
    return Molecule.from_sites(newsites)


def valence_electron(element):
    """
    count valence electrons based on electronic configuration
    if a subshell has > 10 electrons, this subshell is ignored
    """
    configuration = element.data["Electronic structure"]
    list_split = configuration.split('.')

    valence_electrons = 0

    for i in range(len(list_split)):
        if 'sup' in list_split[i]:
            electrons = re.search('<sup>(.*)</sup>', list_split[i])
            if not int(electrons.group(1)) >= 10:
                valence_electrons += int(electrons.group(1))

    return valence_electrons


ZINDO_INP_TEMPLATE = """
 $TITLEI
 
 {title}
 
 $END
 
 $CONTRL
 
 SCFTYP    {scftyp}      
 RUNTYP    {runtyp}        
 ENTTYP    {enttyp}
 UNITS     {units}     
 IPRINT    {iprint}
 INTTYP    {inttyp}
 IAPX      {iapx}
 MULT      {mult}   
 ITMAX     {itmax}   
 SCFTOL    {scftol}
 INTFA(1) = 1.00000 1.26700 0.58500 1.00000 1.00000 1.00000
 ONAME    = {oname}
 
 $END
 
 $DATAIN
 
 {datain}
 
 $END
"""

optional = """
 DYNAL(1) = {nzero} {ns} {nsp} {nspd} {nspdf} {cisize} {nactorb}
 NEL       {nel}

"""


class ZindoJob:

    def __init__(self, jobname, pmgmol, isdimer=False, mol_A=None, mol_D=None, upconvert=True):
        self.jobname = jobname
        self.pmgmol = pmgmol  # add deepcopy?
        self.isdimer = isdimer
        self.mol_A = mol_A
        self.mol_D = mol_D
        if upconvert:
            self.pmgmol = conver2zindo(self.pmgmol)
            self.mol_A = conver2zindo(mol_A)
            self.mol_D = conver2zindo(mol_D)

    @property
    def legit(self):
        if self.isdimer:
            sites = self.mol_A.sites + self.mol_D.sites
        else:
            sites = self.pmgmol.sites
        for s in sites:
            element = Element(s.species_string)
            if element.symbol not in Zindo_elements:
                return False
        return True

    @staticmethod
    def get_valence_electrons(pmgmol):
        """
        pymatgen has a weird `valence` property for element, e.g. for carbon valence is 2
        this is just for neutral mol

        :param pmgmol:
        :return:
        """
        nvelect = 0
        for site in pmgmol.sites:
            element = Element(site.species_string)
            # nvelect += abs(min(element.common_oxidation_states))
            nvelect += valence_electron(element)
        return nvelect

    @staticmethod
    def inpstring(pmgmol, RUNTYP='ENERGY', SCFTYP='RHF', ITMAX=500, SCFTOL=0.0000010, CISIZE=0, ACTSPC=0,
                  ONAME='zindoout'):
        """
        string of input file, charge and mult will be inherited from pmgmol

        :param pmgmol: pymatgen mol object
        :param RUNTYP: can be 'ENERGY' or 'GEO' or 'RPA' or 'CI'
        :param SCFTYP: type of scf
        :param ITMAX: max # of iteration
        :param SCFTOL: scf tol
        :param CISIZE: CI basis size
        :param ACTSPC: # of active orbitals in CI
        :param ONAME: output name
        :return:
        """
        if pmgmol.charge != 0 or pmgmol.spin_multiplicity != 1:
            warnings.warn('W: zindo io can only handle neutral singlet right now!')
        # nelect, ns, nsp, nspd, nspdf = [0]*5
        datain = ''
        for site in pmgmol.sites:
            element = Element(site.species_string)
            # nelect += abs(min(element.common_oxidation_states))
            datain += '{:.6f} {:.6f} {:.6f} {:.6f}\n'.format(site.x, site.y, site.z, element.number)
            # if element.block == 's':
            #     ns += 2
            # elif element.block == 'p':
            #     nsp += 2
            # elif element.block == 'd':
            #     nspd += 1
            # elif element.block == 'f':
            #     nspdf += 1
            # else:
            #     warnings.warn('W: this element has a row number > 7 ??')
        s = ZINDO_INP_TEMPLATE.format(
            title='zindogen', scftyp=SCFTYP, runtyp=RUNTYP, enttyp='COORD', units='ANGS', iprint='1', inttyp='1',
            iapx='3', mult=1, itmax=ITMAX, scftol=SCFTOL,
            # nel=nelect, nzero=0, ns=ns, nsp=nsp, nspd=nspd, nspdf=nspdf, cisize=CISIZE, nactorb=ACTSPC,
            oname=ONAME, datain=datain,
        )
        return s

    def write_single(self, fnprefix, RUNTYP='ENERGY', SCFTYP='RHF', ITMAX=500, SCFTOL=0.0000010, CISIZE=0, ACTSPC=0,
                     ONAME='zindoout'):
        s = self.inpstring(self.pmgmol, RUNTYP, SCFTYP, ITMAX, SCFTOL, CISIZE, ACTSPC, ONAME)
        with open(fnprefix + '.inp', 'w') as f:
            f.write(s)
        return [fnprefix + '.inp']

    def write_dimer(self, fnprefix, RUNTYP='ENERGY', SCFTYP='RHF', ITMAX=500, SCFTOL=0.0000010, CISIZE=0, ACTSPC=0,
                    ONAME='zindoout'):
        if not self.isdimer:
            return
        s_a = self.inpstring(self.mol_A, RUNTYP, SCFTYP, ITMAX, SCFTOL, CISIZE, ACTSPC, ONAME)
        s_d = self.inpstring(self.mol_D, RUNTYP, SCFTYP, ITMAX, SCFTOL, CISIZE, ACTSPC, ONAME)
        s_dimer = self.inpstring(self.pmgmol, RUNTYP, SCFTYP, ITMAX, SCFTOL, CISIZE, ACTSPC, ONAME)
        with open(fnprefix + '_dimer.inp', 'w') as f:
            f.write(s_dimer)
        with open(fnprefix + '_A.inp', 'w') as f:
            f.write(s_a)
        with open(fnprefix + '_D.inp', 'w') as f:
            f.write(s_d)
        return [
            fnprefix + '_dimer.inp',
            fnprefix + '_A.inp',
            fnprefix + '_D.inp',
        ]

    @classmethod
    def dimerjob_from_two_molecules(cls, pmgmol1, pmgmol2, jobname='dimer'):
        dimerpmgmol = Molecule.from_sites(pmgmol1.sites + pmgmol2.sites)
        return cls(jobname, dimerpmgmol, isdimer=True, mol_A=pmgmol1, mol_D=pmgmol2)

    def parse_tmo(self, tmofn='tmo.dat'):
        """
        parse tmo.dat as NAxND array, NA is number of MOs in A, ND is number of MOs in D
        NA, ND is decided by the number of valence eletrons, which is auto-gen by zindo
        # of valence electronis by zindo auto-gen may NOT be identical to the real # of valence electrons!

        :param tmofn:
        :return: data[i][j] is the ti of i+1th MO of A and j+1th MO of B
        """
        if not self.isdimer:
            warnings.warn('W: cannot parse tmo as this is not a dimer run!')
            return None

        try:
            with open(tmofn, 'r') as f:
                ls = [l for l in f.readlines() if l.strip() != '']
        except FileNotFoundError:
            warnings.warn('W: cannot find zindo tmo file {} at {}!'.format(tmofn, os.getcwd()))
            return None

        # this is not safe, use # of electrons identified by zindo instead
        # nmo_a = ZindoJob.get_valence_electrons(self.mol_A)
        # nmo_d = ZindoJob.get_valence_electrons(self.mol_D)

        nmo_a = int(ls[-1].split()[0])
        nmo_d = int(ls[-1].split()[1])

        data = np.empty((nmo_a, nmo_d), dtype=dict)

        for l in ls[3:]:
            imoa, imod, ti, ticm, emoa, emod = [float(number) for number in l.split()]
            imoa = int(imoa)
            imod = int(imod)
            d = dict(ti=ti, emoa=emoa, emod=emod, imoa=imoa, imod=imod)
            data[imoa - 1][imod - 1] = d
        return data, nmo_a, nmo_d

    @staticmethod
    def dimer_run(jobname, wdir, zindobin, zindoctbin, zindolib, pmgmola, pmgmolb):
        """
        perfrom zindo calculation for a dimer system, return parsed tmo.dat as NAxND array

        :param jobname:
        :param wdir: working dir
        :param zindobin: binary path
        :param zindoctbin: binary path
        :param zindolib: dir path
        :param pmgmola:
        :param pmgmolb:
        :return: tmo parsed data, # of AMOs, # of DMOs
        """
        zj = ZindoJob.dimerjob_from_two_molecules(pmgmola, pmgmolb, jobname=jobname)
        whereami = os.getcwd()
        os.chdir(wdir)

        dimer_inps = zj.write_dimer("{}/{}".format(wdir, jobname))
        dimerinp, ainp, dinp = dimer_inps
        aout, dout, dimerout = ["{}/{}".format(wdir, f) for f in ['A.out', 'D.out', 'dimer.out']]
        env = dict(os.environ)
        try:
            ldlibpath = env['LD_LIBRARY_PATH']
        except KeyError:
            ldlibpath = ''
        env['LD_LIBRARY_PATH'] = '{}:'.format(zindolib) + ldlibpath

        ainpf = open(ainp, 'r')
        aoutf = open(aout, 'w')
        aerrf = open(aout+'err', 'w')
        p = subprocess.Popen([zindobin], stdin=ainpf, stdout=aoutf, stderr=aerrf, shell=True, env=env)
        p.wait()
        movefile('{}/mo.out'.format(wdir), '{}/mo_A.out'.format(wdir))
        ainpf.close()
        aoutf.close()
        aerrf.close()

        dinpf = open(dinp, 'r')
        doutf = open(dout, 'w')
        derrf = open(dout+'err', 'w')
        p = subprocess.Popen([zindobin], stdin=dinpf, stdout=doutf, stderr=derrf, shell=True, env=env)
        p.wait()
        movefile('{}/mo.out'.format(wdir), '{}/mo_D.out'.format(wdir))
        dinpf.close()
        doutf.close()
        derrf.close()

        dimerinpf = open(dimerinp, 'r')
        dimeroutf = open(dimerout, 'w')
        dimererrf = open(dimerout+'err', 'w')
        p = subprocess.Popen([zindoctbin], stdin=dimerinpf, stdout=dimeroutf, stderr=dimererrf, shell=True, env=env)
        p.wait()
        data, nmo_a, nmo_d = zj.parse_tmo('tmo.dat')
        dimerinpf.close()
        dimeroutf.close()
        dimererrf.close()

        # p = subprocess.Popen("{} < {} > {}".format(zindobin, ainp, aout), shell=True, env=env)
        # p.wait()
        # movefile('mo.out', 'mo_A.out')
        # p = subprocess.Popen("{} < {} > {}".format(zindobin, dinp, dout), shell=True, env=env)
        # p.wait()
        # movefile('mo.out', 'mo_D.out')
        # p = subprocess.Popen("{} < {} > {}".format(zindoctbin, dimerinp, dimerout), shell=True, env=env)
        # p.wait()
        # data, nmo_a, nmo_d = zj.parse_tmo('tmo.dat')

        os.chdir(whereami)
        return data, nmo_a, nmo_d

    @staticmethod
    def get_hh_coupling(coupling_data, nmo_a, nmo_d):
        """

        :param nmo_a:
        :param nmo_d:
        :param coupling_data: the return value of self.dimer_run()
        :return: the HOMO-HOMO electronic coupling in meV
        """
        nmo_b = nmo_d
        hh_coupling = coupling_data[int(nmo_a / 2 - 1)][int(nmo_b / 2 - 1)]['ti']
        return hh_coupling

    @staticmethod
    def get_ll_coupling(coupling_data, nmo_a, nmo_d):
        """

        :param nmo_a:
        :param nmo_d:
        :param coupling_data: the return value of self.dimer_run()
        :return: the HOMO-HOMO electronic coupling in meV
        """
        nmo_b = nmo_d
        ll_coupling = coupling_data[int(nmo_a / 2)][int(nmo_b / 2)]['ti']
        return ll_coupling
