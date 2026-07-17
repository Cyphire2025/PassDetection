const ISO_CODE_PAIRS = `
ABWAW AFGAF AGOAO AIAAI ALAAX ALBAL ANDAD AREAE ARGAR ARMAM ASMAS ATGAG
AUSAU AUTAT AZEAZ BDIBI BELBE BENBJ BESBQ BFABF BGDBD BGRBG BHRBH BHSBS
BIHBA BLMBL BLRBY BLZBZ BMUBM BOLBO BRABR BRBBB BRNBN BTNBT BWABW CAFCF
CANCA CCKCC CHECH CHLCL CHNCN CIVCI CMRCM CODCD COGCG COKCK COLCO COMKM
CPVCV CRICR CUBCU CUWCW CXRCX CYMKY CYPCY CZECZ DEUDE DJIDJ DMADM DNKDK
DOMDO DZADZ ECUEC EGYEG ERIER ESPES ESTEE ETHET FINFI FJIFJ FLKFK FRAFR
FROFO FSMFM GABGA GBRGB GEOGE GGYGG GHAGH GIBGI GINGN GLPGP GMBGM GNBGW
GNQGQ GRCGR GRDGD GRLGL GTMGT GUFGF GUMGU GUYGY HKGHK HNDHN HRVHR HTIHT
HUNHU IDNID IMNIM INDIN IOTIO IRLIE IRNIR IRQIQ ISLIS ISRIL ITAIT JAMJM
JEYJE JORJO JPNJP KAZKZ KENKE KGZKG KHMKH KIRKI KNAKN KORKR KWTKW LAOLA
LBNLB LBRLR LBYLY LCALC LIELI LKALK LSOLS LTULT LUXLU LVALV MACMO MAFMF
MARMA MCOMC MDAMD MDGMG MDVMV MEXMX MHLMH MKDMK MLIML MLTMT MMRMM MNEME
MNGMN MNPMP MOZMZ MRTMR MSRMS MTQMQ MUSMU MWIMW MYSMY MYTYT NAMNA NCLNC
NERNE NFKNF NGANG NICNI NIUNU NLDNL NORNO NPLNP NRUNR NZLNZ OMNOM PAKPK
PANPA PCNPN PERPE PHLPH PLWPW PNGPG POLPL PRIPR PRKKP PRTPT PRYPY PSEPS
PYFPF QATQA REURE ROURO RUSRU RWARW SAUSA SDNSD SENSN SGPSG SHNSH SJMSJ
SLBSB SLESL SLVSV SMRSM SOMSO SPMPM SRBRS SSDSS STPST SURSR SVKSK SVNSI
SWESE SWZSZ SXMSX SYCSC SYRSY TCATC TCDTD TGOTG THATH TJKTJ TKLTK TKMTM
TLSTL TONTO TTOTT TUNTN TURTR TUVTV TWNTW TZATZ UGAUG UKRUA UMIUM URYUY
USAUS UZBUZ VATVA VCTVC VENVE VGBVG VIRVI VNMVN VUTVU WLFWF WSMWS XKXK
YEMYE ZAFZA ZMBZM ZWEZW
`.trim().split(/\s+/);

const ISO3_TO_ISO2 = new Map(
  ISO_CODE_PAIRS.map((pair) => [pair.slice(0, 3), pair.slice(3)]),
);

const REGION_NAMES = createRegionNames();

export interface PassportCountryOption {
  value: string;
  label: string;
}

export function formatPassportCountry(value: string | null | undefined) {
  const trimmed = value?.trim() ?? "";
  if (!trimmed) return "";

  const code = trimmed.toUpperCase();
  const iso2 = code.length === 2
    ? code
    : code.length === 3
      ? ISO3_TO_ISO2.get(code)
      : undefined;
  if (!iso2 || !/^[A-Z]{2}$/.test(iso2)) return trimmed;

  try {
    return REGION_NAMES?.of(iso2) ?? trimmed;
  } catch {
    return trimmed;
  }
}

export function isRecognizedPassportCountryCode(value: string | null | undefined) {
  const code = value?.trim().toUpperCase() ?? "";
  return /^[A-Z]{2}$/.test(code) || ISO3_TO_ISO2.has(code);
}

export function getPassportCountryOptions(codeLength: 2 | 3): PassportCountryOption[] {
  const options = Array.from(ISO3_TO_ISO2, ([iso3, iso2]) => ({
    value: codeLength === 3 ? iso3 : iso2,
    label: formatPassportCountry(codeLength === 3 ? iso3 : iso2),
  }));
  return options.sort((left, right) => left.label.localeCompare(right.label, "en"));
}

function createRegionNames() {
  try {
    return new Intl.DisplayNames(["en"], { type: "region" });
  } catch {
    return null;
  }
}
