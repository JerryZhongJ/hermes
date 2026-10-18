// Imported from https://github.com/Sable/Ostrich
// Commit: dd06ca4340ecdbc0a795274d826cb5c034a2b9fe
// Source: dynamic-programming/nw/js/needle.js
// Adaptation: benchmarks/speculative/import_ostrich.py
(function () {
  // HBC shells expose Date.now(); SH and V8 also provide performance.now().
  var ostrichNow =
    typeof performance === "undefined" ? Date.now : performance.now.bind(performance);
  var i, j, k, l, idx, index;
  // Copyright 2013 the V8 project authors. All rights reserved.
  // Redistribution and use in source and binary forms, with or without
  // modification, are permitted provided that the following conditions are
  // met:
  //
  //     * Redistributions of source code must retain the above copyright
  //       notice, this list of conditions and the following disclaimer.
  //     * Redistributions in binary form must reproduce the above
  //       copyright notice, this list of conditions and the following
  //       disclaimer in the documentation and/or other materials provided
  //       with the distribution.
  //     * Neither the name of Google Inc. nor the names of its
  //       contributors may be used to endorse or promote products derived
  //       from this software without specific prior written permission.
  //
  // THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
  // "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
  // LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
  // A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
  // OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
  // SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
  // LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
  // DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
  // THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
  // (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
  // OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

  var commonRandom = (function () {
    var seed = 49734321;
    return function () {
      // Robert Jenkins' 32 bit integer hash function.
      seed = (seed + 0x7ed55d16 + (seed << 12)) & 0xffffffff;
      seed = (seed ^ 0xc761c23c ^ (seed >>> 19)) & 0xffffffff;
      seed = (seed + 0x165667b1 + (seed << 5)) & 0xffffffff;
      seed = ((seed + 0xd3a2646c) ^ (seed << 9)) & 0xffffffff;
      seed = (seed + 0xfd7046c5 + (seed << 3)) & 0xffffffff;
      seed = (seed ^ 0xb55a4f09 ^ (seed >>> 16)) & 0xffffffff;
      return seed;
    };
  })();

  var commonRandomJS = function () {
    return Math.abs(commonRandom() / 0x7fffffff);
  };

  /*
   * The MIT License (MIT)
   *
   * Copyright (c) 2014, Erick Lavoie, Faiz Khan, Sujay Kathrotia, Vincent
   * Foley-Bourgon, Laurie Hendren
   *
   * Permission is hereby granted, free of charge, to any person obtaining a copy
   * of this software and associated documentation files (the "Software"), to deal
   * in the Software without restriction, including without limitation the rights
   * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
   * copies of the Software, and to permit persons to whom the Software is
   * furnished to do so, subject to the following conditions:
   *
   * The above copyright notice and this permission notice shall be included in all
   * copies or substantial portions of the Software.
   *
   * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
   * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
   * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
   * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
   * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
   * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
   * SOFTWARE.
   */

  var CHECK_ACCESS_BOUNDS = false;
  var expected_aligned_seq_1_chars =
    "-------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
-----------------------------------------------------------------------------------------------------------------BADAHHAJC-BHBJJC-I-G-IHJCE--HB-IABD--\
D-GBHC-C--A----AJGHCEJI--DJICGJ--EJIHFFAJGBJGBDJB-CIA-D-AHE--AIJ-G-F-FAJEJH--IB-EJ--IBEBE-GGAAIJBBD-I--AE--DJJ-G-EDFGD-HGB--G-IJG--FIIID-G--J-B---C-I-\
-H-BCGGHGHHHAJ--IF------I-----CG-G-CG-----H--F---E--GDI-F-FIFB-DC---BEDCHBGDE-BFE-J--GAAAAAGAGDCDECFGCBE--GIEA-GB--CDAJACFI----I-JDAFJJ-----FCC--CJC-E\
-GDCBBDDIDBG--HDDAFJIDCDC-----HEACCIDBJHJGFGC--CA-IIB-DFE-FEE----I-FBC-IGAAH-GHBJFJH--HIABHFB-E-EDG-----EE--HIBA-BJAHGBJ-IDE--EAEABGHFDAAFBDG-CG-GJAEE\
G--A-G--ACEJ-E-GIGCH---DA---F-JCCGF-HFI-EEE-C-HICHJBEFIHBJFADHBEC-AH-HGGD---AA---B--E--AHJGJ-BH-ICA-FJFHJ---JHFEAIAJGCI------I-GF-FJE-I-I--CIDGGEABGAA\
AD-BBGH---DG-JBBCCI-J-I--BDIE-H--AF--CDCJHDC-FHB--IHCEAJJC-BDEEBDBA-BH--E-C-CDDFJGCGCDGHB-GHBAJCBI-FGH-HGDD-EIBCIIE-CHEIAHE--CJAIFAIBGIJ----AD---ICHEF\
B-F-IGGBE---GD-BJA---DH-I--ADJECA-F--BFAHCFE-JAIEGBEI-EHIF-A--AIBCG--IGCAH-HJEBBBH--D-IAEFFFEHJ-B-I-G-C--D---FC-H-FGBA------H-DB--HAJ---CFFB-EJ---J-FJ\
J---EC-JBIC------D--FBCJ-BIF---ID----DJCE-CI--FIAE------A-JDGE-EIC-ADDDHADDJDHB--GF-AEGHGHIIIDFFHFFE-AFA--GEC-C-IACCHHIJHCGJ-CGJ-B-GE---CIEA-HJGAECC-I\
GAGJF--DCDAGCJFAEIIDA----A--HE------EG-IB-EE--EJ--BIGG-GDFJEEHAIJCDBFGGFFCH--GHJFBBBFE---A--ADBJ-BEHACI-IEFF-BD-FJHAIA--D-DBE--I-HHCIBAGJCGB-J-CHH-B--\
IBFAB-F-ADJHHD-EC-I-IGCG-DAHGIG-GAHDIBCF-FFJDDDABDFEBIHHEGFI--GICD---DAH--EH---H-FJJ-H-I---A-HCFFACFGBFCC----BHHFFJE-BFGCD-G---HHAHHJ--H-HA-HFDGBDFE--\
CBG-F-DAJ----GEBHFBIA-DF---EHDIJH-E-DH-AH-HJC-ED-ADIDADFAJFAFFHAAHGHI---CJJEFDB-CJ--A---EBHE-F-DGABIIHFCFBHE-A--E-EAABIAIC-FCAEEDJHB--CAJE---I---I-DC-\
H--J---EGD-IGDJGJFAJ-FCIJEFB-HI---HHJ-----F-DHGFAABG--I-H-HBIH-BIECD-IDGEBE-IGCFF-IJ-D---DJ-C-CJHBDFJGEE-IGBADHF-IHHIGFBFIDIBDGFHAFH-BFJICBDAGF-DFAIBG\
JFBDEGHAIGE-DEADCEAJDH-E-ICJAGCIIEDBJF-DJFEGGGDC-IGBGJAIAEGFEJFH----EI-DAA-GI-EGGCFEE-FEHHHB---B----B--G-HE-E-H-JBF-D--H-----H-F--FE-HJDJFCJIA-A----E-\
CE----ECHE-IJ-AJHBGA--BFCBFBHCAAGH---GII-B--B-D-G-H-ACGEJ--EDIGGJDBC---G----BBAFBJEJCAJDC--HHGDCCJ-DJAH-CGH-JDEJC-H--F--EDDDEJCAABJ-----A-H----JBCABFH\
IHDHFJBB--JDH-CAJ---GE-E--B-----C-GIDDAHJEG-BA-CBDDJCEAFBDGH-AICIDAE-HAGHJABBGIEDJEGFJ-DD-F-GB--CDHHFADEJEHHBC--A-B---GE-DG--F-BFDAIE---AE-DEEAIBJFBCC\
B--AFADH-E-FBHEFH-DFDFJAEEAGBIE---DDJ-A-IACCIFFC-CBI--IFJA-DDIF--DGE--HG-HIFIGA-J------CHJ-EJ-AHDFE-D--JHG-DHDJCGB-CJE-DFD--------AEDAHFCBIEBICGDH-CDH\
E--GG-AIEJFFJFGBF-CHDJBAGH--I-FGAHAHAAJ-IEIEEJJEE-D-B-I-CAFEHBFIJIEGCEEADGEDJ--H---G-ICCDGCDJDBJI-HJ-----ECEHICE---D--E-CHC-G-J--BFDICBDBF-C-DCD---H--\
---G---J-BB-H-----------------G-D-EHDGFCHCJ-FA---IIDAGIAADFHDEDGE---I--HBJAICBFAFDCACFJF-FGC-I-ABBA-CFHG--HJADAGCHGCJJGJIIJABCACHD-CIDDI--FB--ADEHF--I\
D-BBFCHJ-AACEHBGJFAFBDFFAFBEBCHHA-CDDEIDAAGJEIHHCJIFDAJCB-GIBHBEIHDFJGHEAGE----EFADGJ-GJHGGFBEBBEJHCGIGHHHDFBFCJDAI-BIDJ--IJGGBACAHHCHGI-CHGIAFB-G-JDB\
A--HHAJ-BAEE--I-ABCA---FEJCFAHGJDDJDI-BA-IG-G-IIAD-DIHDHAGGJFFFCAJEJFJA--H-FDEAAEHAAE-EDF-ADIJICFDAFAAGJEEJEEC--IFJ-CFDGJ--BAHBDE-AHF----AHAJBCHAAFD-H\
H-C-FBD-B-FCDF-A--B-B-I-ADFGFIBCB-JIAEF--CGCCG--IGDDHDIJCDBJIFEB-CIBI--D-DA-F--E-FE----JJ---ACDDBJADEEAAEEGGI-HEJJHFC----H-GGE--DFD-IECID-A---F--GEDAJ\
ABDJFD-B-DFC---E-IICGFFBED-BHIBADDIGJ--FBI-CFJDDGHHIGIGH-I--CC-BAF-CFGFCAAHBEDDEDGJCCDFDJJC-HCBHEGJBCJI---AHGJJFCICF--AIDDECADHAG-CIHDDHBCDFDIAJDGGIAE\
J-IIBIHHJ-IDHJBFDDFDICBJEFHGEHEAEHHJIJFAHD-EBAFFBBGE-F---ACGDCE--IFJ--HBDAAJCHBCIADHC----C-H-E----DJ-JEGA-FDJBJBJJJIBAEJ-CJ-HJ-C-HI----EHIFDDE-CJAJCD-\
-HCADHEICIIEFJJ-C-CC-C-IBEF-I---B---IJ-A--EJBBGJGIBC---FCCIB----G--FJHBAD--HCGBBEEABEFFIGABHI-DAGJBACDAGCIAHJE-FBIIFGGIJ-EBDJADJIECF-DGAAGEAJDBIBGB--I\
-F-EBG-HIBHHBG-----A---G-FHAH-DAD-FDC--AJEGIJHJ--GED--IEJIGBFGCEEB-AIAIE-DBE-HFJICGDH-HFI-EGCFBJJAJAIFDE--D--EHCD-DDEICG-FCCHABDFAIDEFB-AABCG--GEHGHJ-\
BFAIGCCGEFDHCGBDGIBHCJFEJCIGBHDDGIHHEFJDBEFE-DAGCAFGCDJEFA---I--EB---GGH---E--E-I-E--D-CHCEFJGAIDCFD--IJ---GDJ-GDEAD---D--EFJBEBEDGFCFAFB---IDGFDEHCGF\
FDCIEABFIBJBICIEDHCFJBJJEJHBHFJBACICEDGH-IBICDCHCDIBJHDEDGGFJAACA-GEIBCGGJCHCIHHGCJFHAHE-GFEAGGBCI-FGGB---I----B-HFGAIJCBJIDBIIJCJIHDAABCBDFBE-EFFGFGI\
-HGGHGHBDFEB--DD-D--EADBCFAHDFIHECICCBHJAHHCJIBEFACFCDJA--EGDG-GABGGJFIIFGBJCJFCHBHEJHFCHADFGGACGIBC-CBAAI-IHCDGDBJDHEIEJHDBHCHADEC-DIGFF--I-DHJ-AGE-J\
-FGJ-----E--CG-BAFJB--I-EFFCHGJ-BCFCB-CCIED---B-AEGF---FJ--C-H---GEJHDFFIECF-D---AG-------E-FGIAFDAH---JF--B---I-H-B--JCD-----G-HB--BHEJ--E-E-E-A---BE\
JGB-----DIA-DAIHFHGFHBEIJEFFDHGGEIJGCCAGGGAH-D----BAI-DBC-ICHIJBH-DAJEFDB-HIIIHEHE-DIABHG-GFIEBA-IBFB-HCAJHGCF--GIJG-IGBFCHADFGCICJGEAHJIFGCIHAGFCCEJC\
-FCEDECBH-JF-EGFCDHJAJBJCHDC-A-BHDDJBDFGDFDGAI-H--BJBBCCE-EFBHCAFCDGJDCCHCEDGCJEEFHHCGJAHJFFECBFFBIEICI-CHD-ICGCJCGCHB-JHEFBAEJHEDJGI-AI-JIB-CEDFHAHGH\
H-E--DE-EGEHCHI--HAH-DAIA-BE-CFDIGHAEJ-EDIGDBAJAJ---H----B-AFFHG--FBGECJJJHFBAEFJBHHCGHDBHB--BDECEDADJDIA-EHIEAGFFCAJ-GIACB-JE---GGI-BDIBA----F--GI-A-\
H--CFCAAIIEAEJGDC-B-BIGCHAE-JAICABIJD-JDEEEAAFIFE-JEAHDDCACDFJEFDECABIJFACBCHEGI--E-EHF-FHAFGJDDGEHDFHHABJDBGIDHJFIACAFBIBAHG-GGEIG-GC-CDFBHCCDGFHJDIA\
CJ-HJABAJDEEJIH--HJA---DJG---F-E---F-I--IBE--GABIECCBCGEADHFAJE-JEBI-BJDCAIDHAAIFE--BCDGIGJDJJAEA----EJDG-IHFIJEHFGCBDEJDE----GHGFEC-CF-FIGIJIADH-EIAE\
HADIAGIHHHBJ-DJGCDHABEIGBBG-EFDIBFAEDAFACEGABFEDFJ-HH-AEBHIBHJIBCEFJ-JEHIFJCBAEI-G-ICBADAAJACIG-E-BABDGIEJIHHAGJC---JGG-HCIGHAE-FAAHF-HCFG--CABFFDGFAE\
FJJCJJAABJFBGFCB--DHEAJACEDCEDBE-CF-E--D-EGHDJEHACDGIBHGHJHAG-C----EJGAJHIGFE---GHEBFJCBGCHBDBIBDECAEJEDHDADGBGE-----J--EH--CHAD-IGBAB-HIHGEJDDCHF-AA-\
-F-D-J---JHB-IJ-BGGEDHDFBAHF-DCDAAHFDAHGID-GEED--AAEB-GJCBJDFAAE--G-AAJDIJ-FGB-E-CDDICEGAJBBIEIBF";
  var expected_aligned_seq_2_chars =
    "-------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
------------------------------------------------------------------------------------------------------------------------------------------------------\
-----------------------------------------------------------------------------------------------------------------BGD-----CEID---DFIJGFI--BEFJGBFI-GDFG\
GJGFFIGIFFADEHBAEG-DE-IFBGJHCGABHE--HDGAEG-J-BHJGHC-AFDFE-EDHAI-FGEFDBG-E-HAGIBIE-FFI-EFEHFCAA--FBDEICBA-IHDAJIDCE-FI-JH-BFAFHC-GJJF-IFDCGACJEAEEJCAIB\
DHFFCBGHI---IJCDIFEEEIHAIDHCJHCBAFACFHJIHHHDEGAAJEACGD-JFJB-GBAGCEEABE--H-FIEAB-EFJCIG-CIAA-HIDCC-C--CB-FIGI-AHGBFEC-JJHBBIBDCJIDJD--JJIHIDEIDCJJCJIFE\
ABD-BCCD-DBGFEDDDHF-GDDDDHGGHAHE-------HJ-BG-JJAAHICAHD-AHBAECDIIIGGBCBICHACED--J-JHJAHI-B-IIAEDEDGFCFIJEEJGHCCAIB---GCJEIDEIFJA-GBDHB--HF--FJI-JFJF-E\
GCBAHFIIACEAGEDGHGAHABBDGDIDFGJ--GFJFFBJJEEGDGIIDDJ-E--HB-CAD--ACFFHCCDDDCAIAAJJJBHAEJHAHJD-FBHDI-ADB-FAJEGDAHDEADA-G-IBHHFEBCDGFBF--DIDFDJCI-GDEAAG-A\
ADIFBDAJJBDGDJ-F--IAJEIFFB-CAFHBIBFGJCDGJ-DDEF-BAGI-----JCIB---BGHAJCHBCEACBFDDF---FC-GHBEFD---CBICF-HJAB-BJEI--IAEFBFEB--EGHC--I-AI-FIJCFGCBDGBCIAAE-\
-EFJI---EJCHBDFFJHICCDAIIHFA--EGACFCGGFG-DF-GJA-EDBEFHEACFGAEJA-ACDHBI-C-HFH----CHAJCJIA-GFI--JIFIIFDICJJDJJIGGEHEIG-AJJHDDIHBDBFIHA-FCHCFGBGEJFBHJCCJ\
JADHECHJB-CBFFDHDDGIFAIJGGFFCHDIDAEBGD-DEJCIHAII-EAGJGBAAFJDIECE-DEAHFCCA-GJ-HCAACFDA-D-G---IDDADDIEDABAJBFJCACBIEGCHAI--CG-BCGJDBAAEDDDCDAAGC-G-E-BEI\
-AF-BEHDHDEIDJ-HE-IDAGBJEEJFHEADHCJFEGFFBCEEIFEJFEB-DGIG----EHJ-JH---GD-GCHIJG-J----AEDACABJADFJAAE---IAGEGFIBDBF--EIACBGFD-EJFIFDH-IHHF-CGBDEIC-AEBEG\
I-FABEFBA-J--DBE-EIHICCCJD-CD-DCBAHCBBGFBFF-----BH-EBI-HE--IHCDIBDABIDBHFJAHJBCHAC--DHJIJBBAJHI-FA--G-ICCAJBJBHHIC-EGBFBIDFGIIBBH-DHJGBAFIAIH-DG---EHD\
CFGFFBD-JHDDIG--H--IJDDFAIBE-G--AEECD-JAHEH-CEEDGA-I------BEIB----G-IJEHC--EIDBFDJIBAJGIE-DEIIJGFA--IH--FBH-GADFJDEFJGI-GCBBI--E--HBEAC-JEGHJICFBIAGIG\
HGAJFDAE-DAI-C-F-F-JBFCI--HBDDIEAJHCJAABABFGGHG---BGDHFHHJHF-HDFI--DAHDFE-EBID---JIJGGAEHDJFCAC-HB-----EIIDB---FJB-HIG---HG--D--HAFGEB-J--BFA-FHD--I-G\
---GE---BGEBDE--I----HBEAI---G-FI---JFJCJ-E-FG--JI--DJ---E--E--HJDJJEIGGHHGGIHA-GCF--DG----BAIJBGJFGBJJFCHECEDHFJAFIDAGHDBAFGHCFBDG-BHADJF--BABAGHIDEG\
C-CGBCEGHAGI-CA--FGAEDBG-BGBH--AGHJFAGICABFFBADBGFDBFCG--HIE-I-GJ--CHIEFEIEIFBJIBJE-C--ICIBABG-HCJBG-EHFBFHFJHEECBHEAFCDEDIDEJ-EAB-IGGGCEIHAGAIJCC-FF-\
-HFHF-IBJEJGHFCF-BFDGEGEHHFAHAAACAFADD-H--BHBADC-DG-H-A-BDCHJEI-ID--IH--H-A-AII-G-AGGJIDCJGEGBIECIIAF-DEJECAACFJEBBHFGGEBHGAAFGBI--IEDDCAJHD---I--FA-C\
-EEAGA--JECF-CA-HJDDDD-A--A--IEJCIDCAFAEIA--IDHCHIAIAFIF-AJGD-FBBFFEAFHDACI-IDHDJGGGGDDDHJAE-ICHC-EJDBCJHGJGA-JC-IJC-EGGFGFIIIFEFJAE-A-F-FGA-IFBDHCCGH\
EHBDGBAI-----FD--EC---B--HEJICFG--JD-AJBIEI-----ACDABJDJCA-E-B-I-I----E-DDECJBCHFJJGHI-GDGBBA-BJIFCJCDFBCEBE-I-EGCJDBGEBC-GEGBJFDFFDICI-FGECAGCFAAJHAA\
FFFGIJAJGCBEHEECAACEGFFFGJFJGBGDDFE-DD-I-IJGFAEDBIIFBCIAFGGGD-DG-IIIIGHHAJFIC-DDFHCHHB-FEF-CAIGACFAICG-GBIGEA-AGCHDC--BEII-AIHAIH-EBIDAICCGBCHAD-HFAJI\
-JIGIC-JBGAC-CAG-G-GBH-FJG--BG-AAJC---I----J----CJ-B--J-BFDIHHBE-A-F----A-EIBIHE-AHHJFG-HAGF---HE--I-IG-----B-----IGCID-HGIJ--BADJ--B-GIJC--I-G-EGCJCF\
EFGHHA-FB--EBIIHA--AJJFFE-HF--G-FGEGIABBDBGFGEGI-DGGI-----GJ--F---E-G-HIBHCFG----HBAEAE-FGGDF-I-FG-F--BJ--J-EIHAI--HCB-G-HBBFHBCECA--EEJJA-A--C--A-DJH\
HDCAF-DCBJHCC-JAEEGJCHCJEDF-F-ADFHA-AEGJAC-CCFJCI---A-IE-D-JI-EBJBIIIFJGIGJCBHJEAIEJDIFJJIAFAC--F-AD-JJH-E--IBHE--H-CBJBBHBBGEGJGFGJB-CI-JABFFFCCGE---\
HB-JCCJCJD-CJEEEACCC-FFHEDBBH-GJCD--JCBGBIGC-ECD-ACICI--JIFACCJIHFJC-D-I----E-HED--CCGI---CEH--H-D----IDFAAAG--FGIHIJEEI-GEIH-HJGFC-HDG-GC-FH-H-GGDC-E\
-FGIBICC-DI-H--CDCFBIABJ---G--JAE-A-I-F--CJEDDCFBBG-GGHHHAC--CEAHIF-DDHFGAH-HH-CIBFHCFBFAIHHJAFFGBDAGJEGECF--F-F---GHA--FC-GH-GCDHGAAHHAHC-GGEGD--JCGB\
IHCAF--I-ID-B--HDADCACEI-EFHGHJHGHHJIJBAHDA--BHJ-I-CHJBBCIIBHHEHGHJF-CB-DIBH-DFAEE--E-F-D---IEDH-J----EG--A--ECF-GIFGBBJCEI--HH-IE-BHDD--G-----C-GBDJI\
FFCE--JA--HH-GCCCCJEJDCDJF-ADGDCDCGDCFHAAEGB-A-BDG-GBBIE-I---DCJE-JH-AI-HGBEBHB-IAGDCGHBCJE-CD---EJ-IA-EAJDIGE--DBAD-II-EB----B-F-ID-FFCAA-HDJJAE--HJE\
BD--GCCG--D----DGGB---B--BI--HDAG--H---DCEC-ID-FCA-CCD-EDAGEHIABEFCJCICHIAFEBIEIIAEGCDBCCCA--GA-AC-DHHIJIIIGHJEGDECDBFBDBEEF-B-BED-BCCH-BJAHI---HEICG-\
GG---A-FI---IAI-BHGF----E-AFHF-BHC-F-DDAJCB-CDI-C-IGEA-ED-DB--HHEJGEFB---J-----H-C-F--HEJIF----IIIJF-BBIAAIEAHFBJHBDHIJCFJ--B--J-JG-D--B-B-FFEJE------\
EA--H-H-DG-BCHGDIDBHEA-B----D-C-E---CBH-A--BJ--E-J---D-AGIE---JG-BAFJG--FD----FD-G----IC-ADBGDA---BFJFBAGIBIHC-----DHEDE-----C-EFEAJDI-FFJAAED-JCEGEFJ\
AGG-GHGHHEJBBFABA-ABEIIJE-FC-F-FB-GCBEDBI-DGAIBGAE-FDAJFJIBIAHCICIE--DCG-EHFHDJJJAGCDAIEEEEDFHI--D-HIJIJFAABJCIIGCGFAIJCDEECEEGIIBGFBHE-HHEIEAACAFJGBE\
-FBAFECCDFAFD--H-HGG-C-I--IFDH--EC-GCFHFGDECGDHAEAFAIGD--JIIH-JB-JD---F-FJHIFGH-AJIDC-B-GJGDIE-AEFFFBAHC--HF-FJBG--GDI-B-C---BG--BJ--A-----C--AGB-DE-C\
HF-ED---HGJFCE--ID-JA-AJ-H-IEAGB--DJ-D--HCDG-IFAFFBJDB--EDE--H-H-ID--DFC-FED--JAE-----J--J---C-GD-IE---ECADFI-----D--BIJ--G--E-HED--IEA-EJI-JCE-I-E---\
-JEJBDEBAG--CFIFBDEHEDBIBDBEGBFCC-C-E-IE--G-B-J-JCCBHFCJIBIJFFAGAJG-G-C---IF--E----CCG----BJJBGEGECA----AFECI--GFGCJJHG--HBGJEHHFFGICBHBBABCJHGJAGICGD\
HGABBCGA-I--E-GFCEBDB-GC-A-DJ--CA-G-DHAD--E---I-EGJ---------BJEF-------FA----EGCJDEJE-FGF--FBAIC-E-D-----JD--I---BI----B-BJH-JFF-CBJG-JC---H-B-G-H-CB-\
CJBHJ-FA--EEECDBGH-AFGDDJFAAHGHEGDCFAIDHI-EACGIFIE-CB----D-CA-EBJAHIHB-DFFBD--AIHEHAB--GIF-----EAHJCJE--GBIGFC--H-AC-CE-CEHBIBGHGB-CHC-EF-D--I-DCGEI-E\
-GD---IHDA--DDJGHD-AG-IFCB-JE--I----D---C--HBF--F-GCCIA--H--H---C---HJEHAF-CG-ECFFJI--A-EA-HCIGHECFA-DF-EEB---FJCFEEJGGFDBI--AEIG--HDAHI-IJJIA--F-GF--\
G------A---BGG-BEGDHE--FHE--E-FEBC-JEBFDFE---J-H-C-G-F-GH-H-DHCEBEHEJDA--I--EBJFFH-BF-C-G--BD--B-AFA---CH-H-GB-EJBFJJJFBEHIEC-ADBIAB-BGDIH-EA--C-FIAEB\
IGCGCJBIDJHBAI-FB-BE---FBAHBHCCIAEBBD----DJG-JGJBGFEBIF-BBADBDAEDBGFAFJHI-HFFBDEFC--BB-GA--B--I--";

  function maximum(a, b, c) {
    var k;
    if (a <= b) k = b;
    else k = a;

    if (k <= c) return c;
    else return k;
  }

  var blosum62 = new Int32Array([
    4, -1, -2, -2, 0, -1, -1, 0, -2, -1, -1, -1, -1, -2, -1, 1, 0, -3, -2, 0, -2, -1, 0, -4, -1, 5,
    0, -2, -3, 1, 0, -2, 0, -3, -2, 2, -1, -3, -2, -1, -1, -3, -2, -3, -1, 0, -1, -4, -2, 0, 6, 1,
    -3, 0, 0, 0, 1, -3, -3, 0, -2, -3, -2, 1, 0, -4, -2, -3, 3, 0, -1, -4, -2, -2, 1, 6, -3, 0, 2,
    -1, -1, -3, -4, -1, -3, -3, -1, 0, -1, -4, -3, -3, 4, 1, -1, -4, 0, -3, -3, -3, 9, -3, -4, -3,
    -3, -1, -1, -3, -1, -2, -3, -1, -1, -2, -2, -1, -3, -3, -2, -4, -1, 1, 0, 0, -3, 5, 2, -2, 0,
    -3, -2, 1, 0, -3, -1, 0, -1, -2, -1, -2, 0, 3, -1, -4, -1, 0, 0, 2, -4, 2, 5, -2, 0, -3, -3, 1,
    -2, -3, -1, 0, -1, -3, -2, -2, 1, 4, -1, -4, 0, -2, 0, -1, -3, -2, -2, 6, -2, -4, -4, -2, -3,
    -3, -2, 0, -2, -2, -3, -3, -1, -2, -1, -4, -2, 0, 1, -1, -3, 0, 0, -2, 8, -3, -3, -1, -2, -1,
    -2, -1, -2, -2, 2, -3, 0, 0, -1, -4, -1, -3, -3, -3, -1, -3, -3, -4, -3, 4, 2, -3, 1, 0, -3, -2,
    -1, -3, -1, 3, -3, -3, -1, -4, -1, -2, -3, -4, -1, -2, -3, -4, -3, 2, 4, -2, 2, 0, -3, -2, -1,
    -2, -1, 1, -4, -3, -1, -4, -1, 2, 0, -1, -3, 1, 1, -2, -1, -3, -2, 5, -1, -3, -1, 0, -1, -3, -2,
    -2, 0, 1, -1, -4, -1, -1, -2, -3, -1, 0, -2, -3, -2, 1, 2, -1, 5, 0, -2, -1, -1, -1, -1, 1, -3,
    -1, -1, -4, -2, -3, -3, -3, -2, -3, -3, -3, -1, 0, 0, -3, 0, 6, -4, -2, -2, 1, 3, -1, -3, -3,
    -1, -4, -1, -2, -2, -1, -3, -1, -1, -2, -2, -3, -3, -1, -2, -4, 7, -1, -1, -4, -3, -2, -2, -1,
    -2, -4, 1, -1, 1, 0, -1, 0, 0, 0, -1, -2, -2, 0, -1, -2, -1, 4, 1, -3, -2, -2, 0, 0, 0, -4, 0,
    -1, 0, -1, -1, -1, -1, -2, -2, -1, -1, -1, -1, -2, -1, 1, 5, -2, -2, 0, -1, -1, 0, -4, -3, -3,
    -4, -4, -2, -2, -3, -2, -2, -3, -2, -3, -1, 1, -4, -3, -2, 11, 2, -3, -4, -3, -2, -4, -2, -2,
    -2, -3, -2, -1, -2, -3, 2, -1, -1, -2, -1, 3, -3, -2, -2, 2, 7, -1, -3, -2, -1, -4, 0, -3, -3,
    -3, -1, -2, -2, -3, -3, 3, 1, -2, 1, -1, -2, -2, 0, -3, -1, 4, -3, -2, -1, -4, -2, -1, 3, 4, -3,
    0, 1, -1, 0, -3, -4, 0, -3, -3, -2, 0, -1, -4, -3, -3, 4, 1, -1, -4, -1, 0, 0, 1, -3, 3, 4, -2,
    0, -3, -3, 1, -1, -3, -1, 0, -1, -3, -2, -2, 1, 4, -1, -4, 0, -1, -1, -1, -2, -1, -1, -1, -1,
    -1, -1, -1, -1, -1, -2, 0, 0, -2, -1, -1, -1, -1, -1, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4,
    -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, -4, 1,
  ]);

  function to_char(i) {
    var characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

    if (i < -1 || i >= 26) {
      throw new Error(
        "ERROR: Invalid conversion to character value, integer '" + i + "' out of range"
      );
    }

    if (i == -1) {
      return "-";
    } else {
      return characters[i];
    }
  }

  function to_int(c) {
    var characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

    if (c == "-") {
      return -1;
    } else {
      var index = characters.indexOf(c);
      if (c < 0 || c > 26) {
        throw new Error("ERROR: Invalid conversion to int value, char '" + c + "' out of range");
      }
      return index;
    }
  }

  var max_rows = 0;
  var max_columns = 0;

  if (CHECK_ACCESS_BOUNDS) {
    var input_index = function (row_index, col_index) {
      if (row_index < 0 || row_index >= max_rows || col_index < 0 || col_index >= max_cols) {
        throw new Error(
          "ERROR: out of bounds access row_index: " + row_index + " col_index: " + col_index
        );
      }
      return row_index * max_cols + col_index;
    };
  } else {
    var input_index = function (row_index, col_index) {
      return row_index * max_cols + col_index;
    };
  }

  function to_int_values(s) {
    var a = [];
    for (var i = 0; i < s.length; ++i) {
      a.push(to_int(s[i]));
    }
    return a;
  }

  function seq_equal(seq_1, seq_2) {
    if (seq_1.length !== seq_2.length) {
      return false;
    }

    for (var i = 0; i < seq_1.length; ++i) {
      if (seq_1[i] !== seq_2[i]) {
        return false;
      }
    }

    return true;
  }

  var expected_aligned_seq_1 = to_int_values(expected_aligned_seq_1_chars);
  var expected_aligned_seq_2 = to_int_values(expected_aligned_seq_2_chars);
  var max_cols = 0;
  var max_rows = 0;

  var reference, input_itemsets, aligned_seq_1, aligned_seq_2, input_seq_1, input_seq_2;

  function needle(penalty, options) {
    for (i = 1; i < max_cols; i++) {
      for (j = 1; j < max_rows; j++) {
        reference[input_index(i, j)] = blosum62[input_seq_1[i] * 24 + input_seq_2[j]];
      }
    }
    for (i = 1; i < max_rows; i++) input_itemsets[input_index(i, 0)] = -i * penalty;
    for (j = 1; j < max_cols; j++) input_itemsets[input_index(0, j)] = -j * penalty;

    if (options.use_parallelizable_version) {
      //Compute top-left matrix
      for (i = 0; i < max_cols - 2; i++) {
        for (idx = 0; idx <= i; idx++) {
          index = (idx + 1) * max_cols + (i + 1 - idx);
          input_itemsets[index] = maximum(
            input_itemsets[index - 1 - max_cols] + reference[index],
            input_itemsets[index - 1] - penalty,
            input_itemsets[index - max_cols] - penalty
          );
        }
      }
      //Compute bottom-right matrix
      for (k = max_rows; k <= 2 * (max_rows - 1); ++k) {
        for (l = 0; l < 2 * (max_rows - 1) - k + 1; ++l) {
          index = input_index(max_rows - 1 - l, k - max_cols + 1 + l);
          input_itemsets[index] = maximum(
            input_itemsets[index - 1 - max_cols] + reference[index],
            input_itemsets[index - 1] - penalty,
            input_itemsets[index - max_cols] - penalty
          );
        }
      }
    } else {
      for (i = 1; i < max_rows; ++i) {
        for (j = 1; j < max_cols; ++j) {
          index = input_index(i, j);
          input_itemsets[index] = maximum(
            input_itemsets[index - 1 - max_cols] + reference[index],
            input_itemsets[index - 1] - penalty,
            input_itemsets[index - max_cols] - penalty
          );
        }
      }
    }
  }

  function runNeedle(dimensions, penalty, options) {
    var default_options = {
      nb_possible_items: 10,
      print_results: false,
      print_intermediary_results: false,
      use_parallelizable_version: true,
    };

    if (dimensions === undefined) {
      dimensions = 4096;
    }

    if (penalty === undefined) {
      penalty = 1;
    }

    if (options === undefined) {
      options = default_options;
    } else {
      for (var n in default_options) {
        if (default_options.hasOwnProperty(n) && !options.hasOwnProperty(n)) {
          options[n] = default_options[n];
        }
      }
    }

    var penalty, idx, index;
    var size;
    var t1, t2;
    var i, j;

    max_rows = dimensions + 1;
    max_cols = dimensions + 1;

    var aligned_seq_size = 2 * dimensions;

    reference = new Int32Array(max_rows * max_cols);
    input_itemsets = new Int32Array(max_rows * max_cols);
    aligned_seq_1 = new Int32Array(aligned_seq_size);
    aligned_seq_2 = new Int32Array(aligned_seq_size);
    input_seq_1 = new Int32Array(max_rows);
    input_seq_2 = new Int32Array(max_cols);

    for (i = 0; i < max_cols; i++) {
      for (j = 0; j < max_rows; j++) {
        input_itemsets[i * max_cols + j] = 0;
      }
    }

    for (i = 0; i < aligned_seq_size; ++i) {
      aligned_seq_1[i] = -1;
      aligned_seq_2[i] = -1;
    }

    input_seq_1[0] = -1;
    for (i = 1; i < max_rows; i++) {
      input_seq_1[i] = Math.abs(commonRandom()) % options.nb_possible_items;
    }
    input_seq_2[0] = -1;
    for (j = 1; j < max_cols; j++) {
      input_seq_2[j] = Math.abs(commonRandom()) % options.nb_possible_items;
    }

    if (options.print_results) {
      print("Computing dynamic programming results");
    }

    var t1 = ostrichNow();
    needle(penalty, options);
    var t2 = ostrichNow();

    var aligned_index_1 = aligned_seq_size - 1;
    var aligned_index_2 = aligned_seq_size - 1;

    for (i = max_rows - 1, j = max_cols - 1; !(i == 0 && j == 0); ) {
      if (i > 0 && j > 0) {
        var nw = input_itemsets[input_index(i - 1, j - 1)] + reference[input_index(i, j)];
        var w = input_itemsets[input_index(i, j - 1)] - penalty;
        var n = input_itemsets[input_index(i - 1, j)] - penalty;
        var n_limit = false;
        var w_limit = false;
        var traceback = maximum(nw, w, n);
      } else if (i === 0) {
        var n_limit = true;
        var w_limit = false;
      } else if (j === 0) {
        var n_limit = false;
        var w_limit = true;
      } else {
        throw new Error("ERROR invalid trace indexes");
      }

      if (n_limit === false && w_limit === false && traceback === nw) {
        aligned_seq_1[aligned_index_1--] = input_seq_1[i--];
        aligned_seq_2[aligned_index_2--] = input_seq_2[j--];
      } else if (n_limit === true || traceback === w) {
        aligned_index_1--;
        aligned_seq_2[aligned_index_2--] = input_seq_2[j--];
      } else if (w_limit === true || traceback === n) {
        aligned_index_2--;
        aligned_seq_1[aligned_index_1--] = input_seq_1[i--];
      } else {
        throw new Error(
          "ERROR n_limit: " + n_limit + " w_limit: " + w_limit + " traceback: " + traceback
        );
      }
    }

    // Hash both complete alignments and check the final DP score.
    // References come from the unmodified upstream JavaScript.
    var expectedAlignment =
      penalty === 1 && options.nb_possible_items === 10
        ? {
            1024: [-685222226, 413116150, 2236],
            64: [1259548095, -940673322, 122],
          }[dimensions]
        : undefined;
    if (expectedAlignment) {
      var hash1 = 0,
        hash2 = 0;
      for (var pos = 0; pos < aligned_seq_1.length; ++pos) {
        hash1 = (hash1 * 31 + aligned_seq_1[pos]) | 0;
        hash2 = (hash2 * 31 + aligned_seq_2[pos]) | 0;
      }
      if (
        hash1 !== expectedAlignment[0] ||
        hash2 !== expectedAlignment[1] ||
        input_itemsets[input_itemsets.length - 1] !== expectedAlignment[2]
      ) {
        throw new Error("Incorrect Needleman-Wunsch alignment or score");
      }
    }
    if (dimensions === 4096 && penalty === 1 && options.nb_possible_items === 10) {
      if (!seq_equal(aligned_seq_1, expected_aligned_seq_1)) {
        throw new Error("ERROR: the aligned sequence 1 is different from the values expected.");
      }

      if (!seq_equal(aligned_seq_2, expected_aligned_seq_2)) {
        throw new Error("ERROR: the aligned sequence 2 is different from the values expected.");
      }
    } else if (!expectedAlignment) {
      print(
        "WARNING: No self-checking for dimension '" +
          dimensions +
          "', penalty '" +
          penalty +
          "', " +
          "and number of possible items '" +
          options.nb_possible_items +
          "'"
      );
    }

    print("The total time spent is " + (t2 - t1) / 1000 + " seconds\n");
    return {
      status: 1,
      options: "runNeedle(" + [dimensions, penalty].join(",") + ")",
      time: (t2 - t1) / 1000,
    };
  }

  const OSTRICH_ARGS = [1024, 1];
  var result = runNeedle(OSTRICH_ARGS[0], OSTRICH_ARGS[1]);
  if (!result || result.status !== 1 || !Number.isFinite(result.time) || result.time <= 0) {
    throw new Error("Invalid benchmark result");
  }
  print("Time: " + result.time * 1000);
})();
