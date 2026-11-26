# Literature Database — Master Index

Tracks every paper processed, its duplicate-check result, and where its
extraction lives. Updated after every paper.

## Standing rule (2026-11-26)
Review papers are excluded from this database, period - never logged, never
summarized, never counted toward the reference expansion. Only original
research papers (experimental or numerical studies reporting new results)
are processed. Before reading a new paper in full, its abstract/intro is
checked first to confirm it is not a review/survey.

## Files in this system
- `existing_74_refs.md` — baseline: the 74 references already live in `Thesis_draft_v1.docx`. Never edited; only checked against.
- `Grand_Literature_Review.docx` — full narrative summary per paper, appended in order received. Template per entry:
  1. **Header**: Year — Title — Scope tag (PTSC+Geo only / PTSC+Nano only / PTSC+Geo+Nano, names given)
  2. **Narrative summary**: geometry/nanofluid studied (figure cited), method, software, Fluent/solver setup in detail (mesh, turbulence model, BCs, y+, discretization, convergence), parameters varied vs. held constant, findings with real numbers/%, visuals/post-processing used
  3. **Tagged fields**: turbulence model, nanofluid property model (Maxwell/Brinkman/etc.), domain type (receiver-only vs. full collector w/ envelope), validation method + deviation %, Re/Tin range, paper-stated limitations
  4. **Overlap flag**: explicit note if it shares our geometry, nanofluid, method, or metric
  5. **Duplicate check**: NEW, or "duplicate of [N]"
  6. Every figure/equation/page cited inline (Fig. N, Eq. N, p. N)
- `Literature_Database.xlsx` — one row per paper, same fields as filterable columns.
- `papers/` — optional per-paper working notes if a summary needs drafting before going into the Grand file.

## Log

| # | Year | Authors (short) | Title (short) | Duplicate check | Status |
|---|------|------------------|----------------|------------------|--------|
| P001 | 2008 | Reddy, Ravi Kumar, Satyanarayana | Energy-Efficient Receiver for PTSC | DUPLICATE of [44] | Logged |
| P002 | 2008 | Reddy, Satyanarayana | Porous Finned Receiver for PTSC | DUPLICATE of [43] | Logged |
| P003 | 2009 | Ravi Kumar, Reddy | Porous Disc Receiver for Solar PTSC | NEW | Logged |
| P004 | 2013 | de Risi, Milanese, Laforgia | Transparent PTC, Gas-Phase Nanofluids | NEW | Logged |
| P005 | 2011 | Munoz, Abanades | Internal Helically Finned Tubes (CFD) | DUPLICATE of [45] | Logged |
| P006 | 2012 | Cheng, He, Cui | Unilateral Longitudinal Vortex Generators | DUPLICATE of [46] | Logged |
| P007 | 2013 | Wang, Liu, Xu | Metal Foams in DSG Receiver Tube | NEW | Logged |
| P008 | 2013 | Ghasemi, Ranjbar, Ramiar | Porous Three Segmental Rings | NEW | Logged |
| P009 | 2014 | Ghadirijafarbeigloo, Zamzamian, Yaghoubi | Louvered Twisted-Tape Receiver Insert | DUPLICATE of [33] | Logged |
| P010 | 2014 | Mwesigye, Bello-Ochende, Meyer | Centrally Placed Perforated Plate Inserts | DUPLICATE of [34] | Logged |
| P011 | 2014 | Song, Dong, Gao, Diao, Zheng, Zhou | Nonuniform Heat Flux + Helical Screw-Tape | DUPLICATE of [36] | Logged |
| P012 | 2014 | Xiao, Zhang, Shao, Li | V-Cavity Absorber with Rectangular Fins | NEW | Logged |
| P013 | 2015 | Diwan, Soni | Wire-Coil Inserts | DUPLICATE of [51] | Logged |
| P014 | 2015 | Nayak, Sinha, Kumar, Kumar | Nanofluid + Nail Twisted Tape (STPTCS) | NEW | Logged |
| P015 | 2016 | Bellos, Tzivanidis, Antonopoulos, Gkinis | Nanofluid + Converging-Diverging Tube | DUPLICATE of [58] | Logged |
| P016 | 2015 | Rios-Iribe et al. | Non-Newtonian Fluid + Twisted Tape (NOT PTSC) | NEW | Logged |
| P017 | 2015 | Huang, Yu, Li, Tao | Dimples vs Protrusions vs Helical Fins | DUPLICATE of [48] | Logged |
| P018 | 2016 | Benabderrahmane, Aminallah, Laouedj, Benazza, Solano | Longitudinal Fins + Al2O3/Cu/SiC/C Nanofluids | DUPLICATE of [59] | Logged |
| P019 | 2016 | Benabderrahmane, Benazza, Aminallah, Laouedj | Baffles + Fullerene/CNT Nanofluid | NEW | Logged |
| P020 | 2017 | Nanan, Thianpong, Pimsarn, Chuwattanakul, Eiamsa-ard | Twisted Cross-Baffle Turbulators (NOT PTSC) | NEW | Logged |
| P021 | 2016 | Jaramillo, Borunda, Velazquez-Lucho, Robles | Low-Enthalpy PTC + Twisted Tape | DUPLICATE of [39] | Logged |
| P022 | 2016 | Mwesigye, Bello-Ochende, Meyer | Wall-Detached Twisted Tape Inserts | DUPLICATE of [35] | Logged |
| P023 | 2016 | Menbari, Alemrajabi, Rezaei | CuO/Water Direct Absorption PTC (DAPTC) | NEW | Logged |
| P024 | 2016 | Basbous, Taqi, Janan | Al2O3/Cu/CuO/Ag Nanofluid Comparison | DUPLICATE of [52] | Logged |
| P025 | 2016 | Zheng, Xu, He | Porous Insert Optimized via Genetic Algorithm + CFD | NEW | Logged |

| P026 | 2017 | Kasaeian, Daneshazarian, Pourfayaz | Glass-Glass Absorber + Nanosilica/MWCNT | NEW | Logged |
| P027 | 2017 | Rawani, Sharma, Singh | Serrated Twisted-Tape Inserts (analytical) | NEW | Logged |
| P028 | 2016 | Toghyani, Baniasadi, Afshari | Integrated Rankine Cycle + Nanofluid PTC (system-level) | DUPLICATE of [53] | Logged |
| P029 | 2017 | Bellos, Tzivanidis, Tsimpoukis | Internally Finned Absorbers (12 configs) | NEW | Logged |
| P030 | 2017 | Gong, Wang, Wang, Tan, Lai, Han | Pin Fin Arrays (bottom periphery only) | NEW | Logged |

| P031 | 2017 | Ghasemi, Ranjbar | Complete Porous Rings | NEW | Logged |
| P032 | 2014 | Rajendran, Ganapathy Sundaram, Jawahar, Pachaiyappan, Naveenraj | SiC Porous Discs (line) + Ag Nanofluid (point focus) | NEW | Logged |
| P033 | 2017 | Xu, Wang, Liu, Zhang, Hassan, Lu | Four-Head Ribbed Tube (NOT PTSC) | NEW | Logged |
| P034 | 2017 | Zhu, Zhu, Zhao | Wavy-Tape Insert | DUPLICATE of [37] | Logged |
| P035 | 2018 | Hatami, Geng, Jing | Porous CPSC Absorber + Cu/Fe3O4/Al2O3/TiO2 Nanofluid | NEW | Logged |
| P036 | 2018 | Bellos, Daniil, Tzivanidis | Multiple Cylindrical Inserts (15 configs) | NEW | Logged |
| P037 | 2018 | Chang, Sciacovelli, Wu, Li, Li, Zhao, Deng, Wang | Rod Inserts + Molten Salt | DUPLICATE of [49] | Logged |
| P038 | 2018 | Bellos, Tzivanidis | Twisted Tape vs Perforated Plate vs Finned (unified comparison) | NEW | Logged |
| P039 | 2018 | Bilal, Arunachala, Sandeep | Fe3O4/Water + Twisted Tape (experimental validation) | NEW | Logged |
| P040 | 2018 | Bellos, Tzivanidis, Tsimpoukis | CuO Nanofluid + Internal Fins (hybrid review/original) | DUPLICATE of [57] | Logged |
| P041 | 2019 | Bellos, Daniil, Tzivanidis | Single Cylindrical Insert (diameter + position) | NEW | Logged |
| P042 | 2020 | Kazemi Moghadam, Mousavi Ajarostaghi, Poncet | Corrugated Tube + Coiled Wire (NOT PTSC) | NEW | Logged |
| P043 | 2020 | Akbarzadeh Hamedani, Mousavi Ajarostaghi, Hosseini | Convergent-Divergent Tube + Al2O3/CuO (NOT PTSC) | NEW | Logged |

| P044 | 2019 | Ahmed, Natarajan | Internal Toroidal Rings in PTSC Receiver | NEW | Logged |
| P045 | 2020 | Korres, Tzivanidis | Bifacial Cavity PTC (small-sized, NOT conventional PTSC) | NEW | Logged |
| P046 | 2020 | Vahabzadeh Bozorg, Doranehgard, Hong, Xiong | Annular Porous Structure + Synthetic Oil-Al2O3 Nanofluid | DUPLICATE of [60] | Logged |
| P047 | 2020 | Khan, Yan, Ali, Amber, Bashir, Akbar, Javed | Comparative Absorber Geometries (Smooth/Fins/Twisted Tape) + Al2O3 Nanofluid | DUPLICATE of [61] | Logged |
| P048 | 2020 | Rostami, Shahsavar, Kefayati, Shahsavar Goldanlou | Corrugated Turbulator + Cu/SBA-15 Hybrid Nanofluid | NEW | Logged |

| P049 | 2020 | Yilmaz, Mwesigye, Goksu | Wire Coil Inserts (Triangle Cross-Section) | NEW | Logged |
| P050 | 2020 | Bellos, Tzivanidis | Internal Fins + Reflecting Shield (Combined Thermal+Optical) | NEW | Logged |
| P051 | 2020 | Laaraba, Mebarki | Longitudinal Fins in Down Half of Receiver Tube | NEW | Logged |
| P052 | 2020 | Arunachala | Twisted Tape Insert (Experimental + Analytical) | NEW | Logged |
| P053 | 2020 | Benabderrahmane, Benazza, Hussein | Central Corrugated Insert (Molten Salt HTF) | NEW | Logged |

| P054 | 2025 | Mousavi Ajarostaghi, Shirzad, Rashidi, Li | Center-Cleared Twisted-Tape + Corrugations + Nanofluid (NOT PTSC) | NEW | Logged |
| P055 | 2021 | Hashemi Karouei, Mousavi Ajarostaghi | Curved Conical Turbulator in Helical Double-Pipe HX (NOT PTSC) | NEW | Logged |
| P056 | 2020 | Noorbakhsh, Zaboli, Mousavi Ajarostaghi | Dual-Side Twisted Tapes in Double-Pipe HX (NOT PTSC) | NEW | Logged |
| P057 | 2020 | Outokesh, Mousavi Ajarostaghi, Bozorgzadeh, Sedighi | Curved-Profile Twisted Tape in Pipe (NOT PTSC) | NEW | Logged |
| P058 | 2020 | Ahmed, Natarajan | Toroidal Rings with Gaseous HTFs (companion to Entry 44) | NEW | Logged |

| P059 | 2020 | Kumar, Reddy | Metal Foam Inserts, Lower-Half, DSG Absorber | NEW | Logged |
| P060 | 2020 | Hosseinalipour, Rostami, Shahriari | Twisted Tape for Circumferential Temp-Difference Reduction (DSG) | NEW | Logged |
| P061 | 2020 | Mahmoud, Abbas, Khudheyer | Internal Conical Pin Fins (lower circumference only) | NEW | Logged |
| P062 | 2020 | Amani, Ebrahimpour, Akbarzadeh, Valipour | Conical Strip Inserts (related to existing ref [50]) | NEW | Logged |
| P063 | 2020 | Peng, Li, Liang | Gradient Metal Foam (GMF), Dual-Layer Pore Density/Porosity | NEW | Logged |

| P064 | 2020 | Mahmoudi, Fazli, Morad, Gholamalizadeh | Forward Perforated Ring Steps, Nanofluid (LFC/linear, not core PTSC) | NEW | Logged |
| P065 | 2021 | Siavashi, Vahabzadeh Bozorg, Hesam Toosi | Nanofluid + Porous Media (Laminar, Buoyancy-Driven) | NEW | Logged |
| P066 | 2021 | Chakraborty, Roy, Das, Gupta | Helical Absorber Tube (whole-tube geometry replacement) | NEW | Logged |
| P067 | 2021 | Mohammed, Vuthaluru, Liu | Conical Turbulators + Hybrid Nanofluids (same group as advisor-baseline ref [40]) | NEW | Logged |
| P068 | 2021 | Saedodin, Zaboli, Mousavi Ajarostaghi | Helical Turbulence-Inducing Elements (simplified constant-flux BC) | NEW | Logged |
| P069 | 2021 | Alnaqi, Alsarraf, Al-Rashed | Two Twisted Tapes, Rotation Direction, Two-Phase Hybrid Nanofluid | NEW | Logged |
| P070 | 2021 | Alqarni, Mahmoud, Algehyne, El-Refaey, El-Shorbagy, Ibrahim | Turbulator with Holes and Ribs, Two-Phase Hybrid Nanofluid | NEW | Logged |
| P071 | 2021 | Afsharpanah, Zabihi Sheshpoli, Pakzad, Mousavi Ajarostaghi | Dual Modified Twisted-Tape Inserts (6-way comparison) | NEW | Logged |
| P072 | 2021 | Pandey, Padhi, Mishra | Arc-Plug Insertion (triangular fin, semi-arc base) | NEW | Logged |
| P073 | 2021 | Fattahi | Twisted Ribs + Wall Rotation + Hybrid Nanofluid (NOT PTSC) | NEW | Logged |
| P074 | 2021 | El-Bakry, Kassem, Hassan | Internal Radiation Heat Shields (optical, not flow promoter) | NEW | Logged |
| P075 | 2021 | Xiao, Liu, Liu, Liu | Inclined Curved-Twisted Baffles (wall-temp-uniformity focus) | NEW | Logged |
| P076 | 2021 | Peng, Li, Hu, Feng | Semi-Annular + Fin Metal Foam Hybrid (SAFM, companion to Entry 63) | NEW | Logged |

| P077 | 2021 | Abed, Afgan, Iacovides, Cioncolini, Khurshid, Nasser | Straight Conical Strip Inserts + SiO2 Nanofluid | NEW | Logged |
| P078 | 2021 | Al-Rashed, Alnaqi, Alsarraf | Finned Rod Turbulator + Hybrid Nanofluid (+ economic analysis) | NEW | Logged |
| P079 | 2022 | Samiezadeh, Khodaverdian, Doranehgard, Chehrmonavari, Xiong | Porous + Finned Receiver + Cu-Al2O3 Hybrid Nanofluid | DUPLICATE of [63] | Logged |
| P080 | 2022 | Aryan, Jannat Alipour, Siavashi, Norouzi | Rotating Absorber + Nanofluid + Porous Lines | NEW | Logged |

| P081 | 2022 | Sheikholeslami, Said, Jafaryar | Wavy Absorber Pipe + CuO Nanofluid (two-phase model) | DUPLICATE of [74] | Logged |
| P082 | 2023 | Vahidinia, Khorasanizadeh, Aghaei | Finned Absorber + Hybrid/Mono Nanofluids (4-way energy/exergy/economic/environmental) | NEW | Logged |

| P083 | 2023 | Pazarlioglu, Ekiciler, Arslan, Mohammed | Elliptical Dimpled Fins (EDF) + Hybrid Nanofluid | NEW | Logged |
| P084 | 2023 | Abbasian Arani, Monfaredi | Acentric Absorber + Insulator Roof + SiC Nanofluid (SPM vs TPM comparison) | NEW | Logged |

| P085 | 2023 | Rezaei Gorjaei, Haghighi Khoshkhoo, Joda, Majidi | Porous Foam, 6 Arrangements x 2 Materials (EuroTrough-150) | NEW | Logged |
| P086 | 2024 | Priyanka, Kashyap, Kumar | V-Ribbed Receiver + 3 Hybrid Nanofluids Comparison | NEW | Logged |

| P087 | 2024 | Panja, Das, Mahesh | Star-Shaped Porous Obstacle + CuO/Al2O3 Nanofluids (laminar, COMSOL) | NEW | Logged |

| P088 | 2024 | Arun, Barik, Ahmad, Alraddadi, Shenashen, Khan | Dimpled Multi-Tube Riser Array + TiO2 Nanofluid (NOT standard single-tube PTSC) | NEW | Logged |
| P089 | 2024 | Saini, Dhar, Powar | Uniform Helical Wire Coil Insert | NEW | Logged |
| P090 | 2024 | Mehta, Subhedar, Panchal, Said, Sharma, Siddiqui, Natrayan, Rosen | Single/Dual Twisted Tape (experimental, energy/exergy/environmental) | NEW | Logged |

| P091 | 2025 | Miansari, Akbari, Moghadasi | Star-Shaped (Cross) Tape Insert + CuO-MgO/Al2O3-MWCNT Hybrid Nanofluids | NEW | Logged |

| P092 | 2025 | Shahdad, Moghimi, Navidbakhsh | Gradient Porous Ring + MWCNT-Al2O3 Hybrid Nanofluid (with exergoeconomic analysis) | NEW | Logged |
| P093 | 2025 | Chakraborty, Das, Algarni, Alqahtani, Irshad | Rotating Tube + Porous Fins + Al2O3-CuO Hybrid Nanofluid | NEW | Logged |
| P094 | 2025 | Kumar, Rajesh Kanna, Ramamurthy, Balasubramanian, Kale, Kilikevicius | Polygonal Rough Surfaces + Hybrid Nanofluids (NOT PTSC, generic duct) | NEW | Logged |
| P095 | 2025 | Kotak, Chotai, Motwani | Cut-Tube Absorber (material-removal strategy, non-evacuated) | NEW | Logged |
| P096 | 2025 | Limboonruang, Oyinola, Harmanto, Phunapai | External Fins (annulus-side, not internal) | NEW | Logged |

| P097 | 2025 | Panja, Das, Mahesh | Inclined Porous Blocks + Nanofluids (companion to Entry 87, same authors) | NEW | Logged |
| P098 | 2025 | Lei, Mohtaram, Li, Su | Dimpled Receivers, Nine-Receiver System-Level Array | NEW | Logged |
| P099 | 2025 | Benabderrahmane, Hussein, Laouedj, Maatki, Kriaa, Alshammari, Kolsi, Abdulameer | Elliptical Absorber Tubes (6 aspect ratios, no nanofluid) | NEW | Logged |
| P100 | 2025 | Sefiani, Bouzit, Elmeriah, Bouddou, Salau, alouache, Berrahi, Feraoun, Benaziza | Elliptical Absorber (2:1) + Al2O3 Nanofluid | NEW | Logged |
| P101 | 2025 | Oumachtaq, Halimi, Ouhadou, El Hassouani, Hajjaj, Messaoudi | U/UU/Helical Internal Tube Exchangers (unconventional receiver architecture) | NEW | Logged |

| P102 | 2025 | Boudjemline, Ali, Mehryan, Ismail, Mahariq, Ben Khedher | Flat Tube + Plus-Shaped Twisted Turbulator (PSTT) | NEW | Logged |
| P103 | 2025 | Byiringiro, Chaanaoui, Hammouti | 3 Fin Configs + Liquid Sodium/Hybrid Nanofluid Comparison | NEW | Logged |
| P104 | 2025 | Khan, Samad, Alamry, Anwar, Norouzi, Mujlid, Ghoushchi | Twisted Triangular Blades Turbulator (near-wall, economic/environmental analysis) | NEW | Logged |
| P105 | 2025 | Samad, Saeidlou, Khan, Alamry, Al-Harbi, Sharifpur, Ghoushchi | Semi-Corrugated Tube + Shell Form Cone Turbulator + CuO Nanofluid | NEW | Logged |
| P106 | 2025 | Gholinia, Ghobadi, Shahcheraghi, Armin | Anchor-Shaped Turbulators + Eco-Friendly GAGNPs/H2O Nanofluid | NEW | Logged |

**Not processed**: `b3a937f8-two_twisted_is_similar_to_previous_paper.pdf` is the identical paper already logged as Entry 69 (Alnaqi, Alsarraf, Al-Rashed 2021, SETA 47:101331, two twisted tape inserts) - confirmed via title/author/journal match, not re-logged (user's own filename flagged this).

**Not processed**: `d57b9900-Experimental_not_PTC_should_be_deleted.pdf` was excluded from this batch per its own filename flag (not a PTC paper, marked for deletion) - not read or logged.

**Not processed**: `c5ef5f0a-Cu_Fe3O4_Al2O3_TiO2.pdf` in this batch is a duplicate re-upload of the same paper already logged as Entry 35 (Hatami, Geng, Jing 2018) - not re-logged.

**Not processed**: `1afdc7c8-A_Novel_Solution_Methodology...pdf` failed to read (corrupted/not a valid PDF file) - flagged to user, needs re-upload. `d454e451-Heat_transfer_enhancement...longitudinal_fins_and_nanofluids.pdf` in this batch is the same paper as Entry 18 (Benabderrahmane et al. 2016, JTS) - not re-logged. `5e61ec71-A_Novel_Solution_Methodology...pdf` (a second re-upload attempt of the same corrupted file) ALSO failed to read - still needs a working re-upload.
