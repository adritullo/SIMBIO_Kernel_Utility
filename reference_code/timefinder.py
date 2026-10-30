import spiceypy as sp
import numpy as np




def timefinder(path2meta, camera, dvec, observer, target, target_frame, method, rBody, step, minlat, maxlat, minlong, maxlong, t0, tf, firstalwaysgood=False):

    ### Load Kernels
    sp.furnsh(path2meta)

    t0 = sp.str2et(t0)
    tf = sp.str2et(tf)

    # dimensione_pixel_sul_sensore
    # STC: 10 micron = 10e-6 m
    dimensione_pixel_sul_sensore = 1e-5

    if camera.split("_")[-1] == "FPAN":
        focal = 0.8
    elif camera.split("_")[-1] == "P700":
        focal = 0.095
    elif camera.split("_")[-1] == "FPA":
        focal = 0.160
        dimensione_pixel_sul_sensore = 4e-5
    elif camera.split("_")[-1] == "JANUS":
        dimensione_pixel_sul_sensore = 0.007
        focal = 467
    else:
        dimensione_pixel_sul_sensore = float(input("Dimensione pixel sul sensore?"))
        focal = float(input("Focal Length?"))

    # Focal lenght
    # HRIC 0.8 m


    abcorr = "NONE"
    #abcorr = "CN+S"
    crdsys = "GEODETIC"
    adjust = 0.

    nintvls = 1000 #


    if minlat > maxlat:
        a = minlat
        minlat = maxlat
        maxlat = a

    if minlong > maxlong:
        a = minlong
        minlong = maxlong
        maxlong = a


    minlatrad = np.deg2rad(minlat)
    maxlatrad = np.deg2rad(maxlat)
    minlongrad = np.deg2rad(minlong)
    maxlongrad = np.deg2rad(maxlong)

    cnfine = sp.stypes.SPICEDOUBLE_CELL(2)
    sp.wninsd(t0, tf, cnfine)


    dref = camera


    (result1) = sp.gfsntc(target, target_frame, method, abcorr, observer, dref, dvec, crdsys, 'LATITUDE', ">", minlatrad, adjust, step, nintvls, cnfine)
    #tipo = sp.gfsntc(target, target_frame, method, 'LT+S', observer, frame , dvec=bsight, adjust=0, nintvls=500, crdsys="GEODETIC", coord="LATITUDE", relate=">", refval=np.deg2rad(latitudemax), step=30, cnfine=window)

    winsiz = sp.wncard(result1)
    # print(winsiz)

    (result2) = sp.gfsntc(target, target_frame, method, abcorr, observer, dref, dvec, crdsys, 'LATITUDE', "<", maxlatrad, adjust, step, nintvls, result1)
    winsiz = sp.wncard(result2)
    #print(winsiz)

    (result3) = sp.gfsntc(target, target_frame, method, abcorr, observer, dref, dvec, crdsys, 'LONGITUDE', ">", minlongrad, adjust, step, nintvls, result2)
    winsiz = sp.wncard(result3)
    #print(winsiz)

    (result4) = sp.gfsntc(target, target_frame, method, abcorr, observer, dref, dvec, crdsys, 'LONGITUDE', "<", maxlongrad, adjust, step, nintvls, result3)
    winsiz = sp.wncard(result4)
    #print(winsiz)


    tdbfmt = "YYYY MON DD HR:MN:SC.### (TBD :"

    ntime = 0
    while True:
        et = result4[ntime]
        camera_id = sp.bodn2c(camera)
        (shape, frame, bsight, vectors, bounds) = sp.getfov(camera_id, 100)
        pixel_samples = int(sp.gdpool('INS' + str(camera_id) + '_PIXEL_SAMPLES', 0, 1))
        pixel_lines = int(sp.gdpool('INS' + str(camera_id) + '_PIXEL_LINES', 0, 1))
        nx, ny = (pixel_samples, pixel_lines)
        x = np.linspace(bounds[0][0], bounds[2][0], nx)
        y = np.linspace(bounds[0][1], bounds[2][1], ny)
        ibsight = [x[int((nx / 2) - 1)], y[int((ny / 2) - 1)], bsight[2]]  # generalize fatto
        (spoint, trgepc, srfvec) = sp.sincpt(method, target, et, target_frame, 'NONE', observer, frame, ibsight)
        #print(srfvec)
        (trgepc_ILLUM, srfvec_ILLUM, phase_ILLUM, solar_ILLUM, emissn, visiblef_ILLUM, iluminatedf_ILLUM) = sp.illumf(method,
                                                                                                                      target,
                                                                                                                      'SUN', et,
                                                                                                                      target_frame,
                                                                                                                      'LT+S',
                                                                                                                      observer,
                                                                                                                      spoint)
        solar_incidence = np.rad2deg(solar_ILLUM)

        if solar_incidence < 90:
            #EMISSION
            (srad, slon, slat) = sp.reclat(spoint)
            lon = slon * sp.dpr()
            lat = slat * sp.dpr()

            pos_camera = sp.spkpos(observer, et, target_frame, 'NONE', target)[0]
            (r, sslon, sslat) = sp.reclat(pos_camera)
            latsubspace = sslat * 180 / np.pi
            lonsubspace = sslon * 180 / np.pi

            quota_volo = r-(rBody/1000)
            quota_volo_m = quota_volo*1000

            new_spoint_vec = ((spoint[0] * 1e3), (spoint[1] * 1e3), (spoint[2] * 1e3))
            new_srfvec = ((srfvec[0]), (srfvec[0]), (srfvec[0]))
            new_dist = sp.vnorm(srfvec)



            squared_dist = np.sum((pos_camera - spoint) ** 2, axis=0)
            dist = np.sqrt(squared_dist)*1000
            risoluzione = (dist * dimensione_pixel_sul_sensore) / focal

            #print("ifov: ", dimensione_pixel_sul_sensore/focal)
            ifov_met = dimensione_pixel_sul_sensore/focal
            ifov_gradi = (360/(2*rBody*np.pi)) * ifov_met
            ifov_rad = np.deg2rad(ifov_gradi)

            #print("IFOV:", ifov_rad*1000000, "microrad", ifov_gradi)

            #risoluzione = ((dist / quota_volo_m) * (np.cos(emissn))) * risoluzione
            #risoluzione = (quota_volo_m * dimensione_pixel_sul_sensore) / focal

            risoluzione = ((dist * dimensione_pixel_sul_sensore) / focal) / (np.cos(emissn))

            obsCode = sp.bodn2c(observer)
            trgCode = sp.bodn2c(target)

            state, onewaylighttime = sp.spkez(obsCode, et, "J2000",'NONE', trgCode)

            raggioorbita = (onewaylighttime * sp.clight()) #km
            #print(state * 3600)

            velx, vely, velz = state[3:]

            vel_inst_orbita = np.sqrt((velx**2) + (vely**2) + (velz**2))  # km/s

            vel_inst_surface = (vel_inst_orbita * (rBody/1000)) / (raggioorbita)

            #TRUE ANOMALY
            sunCode = sp.bodn2c("SUN")
            sunrelated_state, sunrelated_onewaylighttime = sp.spkez(obsCode, et, "J2000", 'LT+S', sunCode)

            print(sunrelated_state)

            mu_GP_SUN = 1.32712440018E11
            mu_GP_MERCURY = 2.20319E4
            conics = sp.oscltx(sunrelated_state,et,mu_GP_SUN)
            RP, ECC, INC, LNODE, ARGP, M0, T0, MU, NU, A, TAU = conics
            '''RP      Perifocal distance.
                  ECC     Eccentricity.
                  INC     Inclination.
                  LNODE   Longitude of the ascending node.
                  ARGP    Argument of periapsis.
                  M0      Mean anomaly at epoch.
                  T0      Epoch.
                  MU      Gravitational parameter.
                  NU      True anomaly at epoch.
                  A       Semi-major axis. A is set to zero if
                          it is not computable.
                  TAU Orbital period. Applicable only for
                          elliptical orbits. Set to zero otherwise.'''
            #print("SUN_MU: ", np.rad2deg(NU))
            #conics = sp.oscltx(sunrelated_state,et,mu_GP_MERCURY)
            #RP, ECC, INC, LNODE, ARGP, M0, T0, MU, NU, A, TAU = conics
            #print("MERCURY_MU: ", )

            true_anomaly = np.rad2deg(NU)



            #vel on ground =  vel in orbita * raggioplan / raggioorbita

            '''
            #CALCOLO DI FASE E INCIDENZA (inglobato in illumf)
            illumination_condition = sp.ilumin(method, target, result4[ntime], target_frame, "LT+S", observer, spoint)
            print(illumination_condition)
            '''
            phase_angle = np.rad2deg(phase_ILLUM)

            emission_angle = np.rad2deg(emissn)

            outdict = {"time":f"{sp.timout(result4[ntime],tdbfmt)} {result4[ntime]})",
                       "time_et": result4[ntime],
                       "Phase":phase_angle,
                       "Incidence":solar_incidence,
                       "Emission":emission_angle,
                       "Rectangular_coordinates":spoint,
                       "CPt_coordinates":[lon,lat],
                       "Resolution":risoluzione,
                       "Flight altitude":quota_volo,
                       "Distance_from_Boresight":dist/1000,
                       "Orbital_Velocity":vel_inst_orbita,
                       "Ground_Velocity":vel_inst_surface,
                       "True_Anomaly": true_anomaly}


            print(f'{camera}'
                  f'\nPrimo momento disponibile: {sp.timout(result4[ntime],tdbfmt)} {result4[ntime]}) '
                  f'\n Phase [deg]: {phase_angle} '
                  f'\n Solar Incidence [deg]: {solar_incidence}'
                  f'\n Emission [deg]: {emission_angle} '
                  f'\n Rectangular coordinates: {spoint})'
                  f'\n Central point coordinates: Long {"%.3f" % (lon)}° Lat {"%.3f" % (lat)}° '
                  f'\n Sub Spacecraft coordinates: Long {"%.3f" % lonsubspace}° Lat {"%.3f" % latsubspace}°'
                  f'\n Ground Resolution [m/px]: {"%.2f" % risoluzione} \n Flight altitude [km]: {"%.2f" % (float(dist)/1000)}'
                  f'\n Orbital Velocity [km/s]: {vel_inst_orbita}'
                  f'\n Velocity on ground [km/s]: {vel_inst_surface}'
                  f'\n True anomaly [deg]: {true_anomaly}'
                  )

            if firstalwaysgood:
                return outdict
                break

            risposta = input("Prossimo? (y/n)")
            ntime +=1
            if risposta == "n":
                return outdict
                break
        else:
            ntime += 1


    sp.kclear()



if __name__ == '__main__':
    '''
    path2meta = 'E:/Janus/JUICE/kernels/mk/juice_plan.tm'
    camera = 'JUICE_JANUS'  # 'MPO_SIMBIO-SYS_STC-H_P700 & MPO_SIMBIO-SYS_STC-L_P700' & MPO_SIMBIO-SYS_HRIC_FPAN
    target = 'MOON'
    target_frame = 'IAU_MOON'
    observer = 'JUICE'
    method = 'ELLIPSOID'
    rBody = 1738100  # m
    dvec = [0, 0, 1]

    '''
    path2meta = r"F:\BEPICOLOMBO_ops\data\SPICE\BEPICOLOMBO\kernels\mk\bc_nadir_plan_ES.tm".replace("\\","/")
    #pathtometa = r"F:\BEPICOLOMBO_ops\data\SPICE\BEPICOLOMBO\kernels\mk\bc_plan_v431_20250709_001_ES.tm"
    camera = 'MPO_SIMBIO-SYS_STC-L_P700'  # 'MPO_SIMBIO-SYS_STC-H_P700 & MPO_SIMBIO-SYS_STC-L_P700' & MPO_SIMBIO-SYS_HRIC_FPAN & MPO_SIMBIO-SYS_VIHI_FPA
    dvec = [0, 0, 1]
    observer = 'MPO'
    target = 'MERCURY'
    target_frame = 'IAU_MERCURY'
    method = 'Ellipsoid'
    rBody = 2439400  # m

    step = 30 #espresso in secondi

    #center: 32.3°, 42.0°
    minlat =  -89
    maxlat = 89
    minlong = -179 # -179+179 per evitare rounding errors in 180
    maxlong = 179
    #t0 = '2026 jun 28 18:00:00'
    #tf = '2026 jul 2 17:28:38'

    #CUstom
    "2027 APR 16 20:06:31.000027"
    "2027 APR 06 07:48:34.000"
    t0 = "2027 APR 06 07:47:34.000"
    tf = "2027 APR 06 07:49:34.000"

    "2027 APR 20 00:36:11.000049"

    '2027-05-18 T02:10:30.00'
    '2027-04-16 T20:06:31.000027'

    #APH1
    #t0 = '2027-06-02 T16:48:00.00'
    #tf = '2027-07-03 T20:23:00.00'

    #APH2
    #t0 = '2027-08-29 T16:05:00.00'
    #tf = '2027-09-29 T19:37:00.00'

    #TERM 1
    #t0 = '2027-04-06 T21:06:59.00'
    #tf = '2027-04-30 T16:48:00.00'

    #TERM 2
    #t0 = '2027-04-30 T21:06:59.00'
    #tf = '2027-06-02 T16:48:00.00'

    #TERM 3
    #t0 = '2027-07-03 T20:23:00.00'
    #tf = '2027-07-29 T16:05:00.00'

    #TERM 4
    #t0 = '2027-03-27 T06:34:00.00'
    #tf = '2027-04-06 T21:06:59.00'


    #t0 = sp.str2et('')
    #tf = sp.str2et()

    ''' 59.7°, 57.3°'''

    #| 2027-04-06 T21:06:59.00 | 2027-06-02 T16:48:00.00 |



    '''
    | End           | Start     |                         |             |
    | ------------- | --------- | ----------------------- | ----------- |
    | Commissioning | Half APH0 | 2027-03-22 T06:34:00.00 | 860317688.2 |
    | APH0          | Termin. 1 | 2027-04-06 T21:06:59.00 | 865226888.2 |
    | Termin. 2     | APH1      | 2027-06-02 T16:48:00.00 | 865226949.2 |
    | APH1          | Termin.3  | 2027-07-03 T20:23:00.00 | 867918249.2 |
    | Termin.4      | APH2      | 2027-08-29 T16:05:00.00 | 872827569.2 |
    | APH2          | Termin.4  | 2027-09-29 T19:37:00.00 | 875518689.2 |
    '''



    timefinder(path2meta, camera, dvec, observer, target, target_frame, method, rBody, step, minlat, maxlat, minlong, maxlong, t0, tf)
