import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import math, os

OUT = "/tmp/claude-0/-home-user-dhagax100/1721b0cc-67bb-5910-9b81-140c886e3b96/scratchpad/figs"

def rho(T): return 1105.7-0.41535*T-0.00060616*T**2
def mu(T):  return 0.084866-0.00055412*T+1.3882e-6*T**2-1.566e-9*T**3+6.672e-13*T**4
def kf(T):  return 0.19002-0.00018752*T-5.7534e-10*T**2
def cp(T):  return 1107.8+1.708*T

dti=0.066
A_sm=math.pi/4*dti**2
A_en=math.pi/4*(dti**2-0.015**2)+math.pi/4*0.0129**2

# baseline anchor from Run 0 CFD
Tb0=(500+519.09171)/2
r0,m0,k0,c0=rho(Tb0),mu(Tb0),kf(Tb0),cp(Tb0)
u0=0.41748124/(r0*A_sm)
f0=2*0.07788985/(r0*u0**2)
Nu0=(35607.497/(660.03433-Tb0))*dti/k0
Pr0=m0*c0/k0
fD0=(0.79*math.log(10000)-1.64)**-2
NuG0=(fD0/8)*9000*Pr0/(1+12.7*math.sqrt(fD0/8)*(Pr0**(2/3)-1))
Cf=f0/(fD0/4); CNu=Nu0/NuG0

runs=[(1,200,5000,0.20524493,538.70755,776.22613,0.036590281,37764.874),
(2,200,10000,0.41048987,519.39508,675.42972,0.11466769,37764.873),
(3,200,15000,0.6157348,512.94033,628.58348,0.22848134,37764.874),
(4,200,20000,0.82097973,509.6559,600.03473,0.42980233,37755.560),
(5,200,25000,1.0262247,507.76871,586.92221,0.54258332,37764.875),
(6,200,30000,1.2314696,506.47481,575.93832,0.73434832,37764.875),
(7,300,5000,0.20524493,538.70629,777.08046,0.036206036,37764.875),
(8,300,10000,0.41048986,519.39473,676.26732,0.11300648,37764.878),
(9,300,15000,0.61573479,512.94018,629.42261,0.22481585,37764.877),
(10,300,20000,0.82097972,509.70877,603.58067,0.36636378,37764.875),
(11,300,25000,1.0262246,507.76866,587.56358,0.53314748,37764.875),
(12,300,30000,1.2314696,506.47478,576.52539,0.7212604,37764.875),
(13,400,5000,0.20524493,538.70604,777.46422,0.036044457,37764.874),
(14,400,10000,0.41048987,519.39471,676.58422,0.11250944,37764.876)]

D={200:{'Re':[], 'fr':[], 'nr':[], 'pec':[]},300:{'Re':[], 'fr':[], 'nr':[], 'pec':[]},400:{'Re':[], 'fr':[], 'nr':[], 'pec':[]}}
for run,Pt,Re,mdot,Tout,Tw,tau,q in runs:
    Tb=(500+Tout)/2
    r,m,k,c=rho(Tb),mu(Tb),kf(Tb),cp(Tb)
    u=mdot/(r*A_en)
    f=2*tau/(r*u**2)
    Nu=(q/(Tw-Tb))*dti/k
    Pr=m*c/k
    fD=(0.79*math.log(Re)-1.64)**-2
    fo=Cf*fD/4
    Nuo=CNu*(fD/8)*(Re-1000)*Pr/(1+12.7*math.sqrt(fD/8)*(Pr**(2/3)-1))
    fr=f/fo; nr=Nu/Nuo
    D[Pt]['Re'].append(Re); D[Pt]['fr'].append(fr); D[Pt]['nr'].append(nr)
    D[Pt]['pec'].append(nr/fr**(1/3))

SERIES=[(200,"#2f6fd0","s",9.5,2.4,"$P_t$ = 200 mm  ($P_t/d_{ti}$ = 3.03)"),
        (300,"#d94801","o",7.0,2.0,"$P_t$ = 300 mm  ($P_t/d_{ti}$ = 4.55)"),
        (400,"#00916e","^",5.0,1.6,"$P_t$ = 400 mm  ($P_t/d_{ti}$ = 6.06)")]

plt.rcParams.update({
    "font.family":"DejaVu Serif","font.size":11,
    "axes.linewidth":1.0,"axes.edgecolor":"#222222",
    "xtick.direction":"in","ytick.direction":"in",
    "xtick.top":True,"ytick.right":True,
    "xtick.major.size":5,"ytick.major.size":5,
    "xtick.minor.size":2.8,"ytick.minor.size":2.8,
    "xtick.minor.visible":True,"ytick.minor.visible":True,
    "figure.facecolor":"white","axes.facecolor":"white",
})

def panel(key, ylabel, fname, ylim, ymaj, hline=None):
    fig, ax = plt.subplots(figsize=(6.1,4.5), dpi=300)
    for i,(Pt,color,mark,ms,lw,lab) in enumerate(SERIES):
        ax.plot(D[Pt]['Re'], D[Pt][key], color=color, marker=mark, markersize=ms,
                linewidth=lw, markerfacecolor="white", markeredgecolor=color,
                markeredgewidth=1.7, label=lab, clip_on=False, zorder=3+i)
    if hline is not None:
        ax.axhline(hline, color="#9a9a9a", linewidth=1.0, linestyle=(0,(5,4)), zorder=1)
        ax.annotate("no enhancement", xy=(30000, hline), xytext=(-4,4),
                    textcoords="offset points", ha="right", va="bottom",
                    fontsize=8.5, color="#6b6b6b")
    ax.set_xlim(4000,31000); ax.set_ylim(*ylim)
    ax.set_xticks([5000,10000,15000,20000,25000,30000])
    ax.xaxis.set_minor_locator(MultipleLocator(2500))
    ax.yaxis.set_major_locator(MultipleLocator(ymaj))
    ax.set_xlabel("Re number", fontsize=11.5, labelpad=6)
    ax.set_ylabel(ylabel, fontsize=12.5, labelpad=6)
    ax.tick_params(labelsize=10)
    leg = ax.legend(loc="upper right", frameon=True, fontsize=9.2,
                    handlelength=2.4, borderpad=0.55, labelspacing=0.5)
    leg.get_frame().set_edgecolor("#555555"); leg.get_frame().set_linewidth(0.8)
    leg.get_frame().set_facecolor("white")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT,fname), dpi=300, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)

panel('fr',  r"$f/f_o$",     "fig_a_friction.png", (1.32,1.78), 0.1)
panel('nr',  r"$Nu/Nu_o$",   "fig_b_nusselt.png",  (0.72,1.38), 0.1, hline=1.0)
panel('pec', r"PEC",         "fig_c_pec.png",      (0.68,1.18), 0.1, hline=1.0)
print("figures written")
for Pt in (200,300,400):
    print(Pt, [f"{v:.3f}" for v in D[Pt]['pec']])

# ---------- composite figure in the mirror's Figure 4-1 layout ----------
import matplotlib.gridspec as gridspec
fig = plt.figure(figsize=(10.6,8.6), dpi=300)
gs = gridspec.GridSpec(2,4, figure=fig, hspace=0.34, wspace=0.75,
                       left=0.075, right=0.985, top=0.985, bottom=0.075)
axes = [fig.add_subplot(gs[0,0:2]), fig.add_subplot(gs[0,2:4]), fig.add_subplot(gs[1,1:3])]
spec = [('fr', r"$f/f_o$", (1.32,1.78), None, "(a)"),
        ('nr', r"$Nu/Nu_o$", (0.72,1.38), 1.0, "(b)"),
        ('pec', r"PEC", (0.68,1.18), 1.0, "(c)")]
for ax,(key,ylab,ylim,hl,tag) in zip(axes,spec):
    for i,(Pt,color,mark,ms,lw,lab) in enumerate(SERIES):
        ax.plot(D[Pt]['Re'], D[Pt][key], color=color, marker=mark, markersize=ms,
                linewidth=lw, markerfacecolor="white", markeredgecolor=color,
                markeredgewidth=1.7, label=lab, clip_on=False, zorder=3+i)
    if hl is not None:
        ax.axhline(hl, color="#9a9a9a", linewidth=1.0, linestyle=(0,(5,4)), zorder=1)
    ax.set_xlim(4000,31000); ax.set_ylim(*ylim)
    ax.set_xticks([5000,10000,15000,20000,25000,30000])
    ax.xaxis.set_minor_locator(MultipleLocator(2500))
    ax.yaxis.set_major_locator(MultipleLocator(0.1))
    ax.set_xlabel("Re number", fontsize=10.5, labelpad=5)
    ax.set_ylabel(ylab, fontsize=12, labelpad=5)
    ax.tick_params(labelsize=9)
    leg=ax.legend(loc="upper right", frameon=True, fontsize=7.4,
                  handlelength=2.1, borderpad=0.42, labelspacing=0.38)
    leg.get_frame().set_edgecolor("#555555"); leg.get_frame().set_linewidth(0.7)
    ax.text(0.5,-0.20,tag,transform=ax.transAxes,ha="center",va="top",fontsize=11.5)
fig.savefig(os.path.join(OUT,"fig_composite.png"), dpi=300, bbox_inches="tight", facecolor="white")
plt.close(fig)
print("composite written")
