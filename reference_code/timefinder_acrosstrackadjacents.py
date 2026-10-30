import spiceypy as sp
import numpy as np



def timefinderAcTrOrbits(path2meta, camera, dvec, observer, target, target_frame, method, rBody, step, minlat, maxlat, minlong, maxlong, t0, tf, longdirection, minoverlap, maxoverlap, pixel_acrosstrack):

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

    else:
        dimensione_pixel_sul_sensore = input("Dimensione pixel sul sensore?")
        focal = input("Focal Length?")

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
        print(srfvec)
        (trgepc_ILLUM, srfvec_ILLUM, phase_ILLUM, solar_ILLUM, emissn, visiblef_ILLUM, iluminatedf_ILLUM) = sp.illumf(method,
                                                                                                                      target,
                                                                                                                      'SUN', et,
                                                                                                                      target_frame,
                                                                                                                      'LT+S',
                                                                                                                      observer,
                                                                                                                      spoint)
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

        squared_dist = np.sum((pos_camera - spoint) ** 2, axis=0)
        dist = np.sqrt(squared_dist)*1000
        risoluzione = (dist * dimensione_pixel_sul_sensore) / focal
        risoluzione = ((dist / quota_volo_m) * (np.cos(emissn))) * risoluzione
        #risoluzione = (quota_volo_m * dimensione_pixel_sul_sensore) / focal

        obsCode = sp.bodn2c(observer)
        trgCode = sp.bodn2c(target)

        state, onewaylighttime = sp.spkez(obsCode, et, "J2000",'NONE', trgCode)

        raggioorbita = (onewaylighttime * sp.clight()) #km
        #print(state * 3600)

        velx, vely, velz = state[3:]

        vel_inst_orbita = np.sqrt((velx**2) + (vely**2) + (velz**2))  # km/s

        vel_inst_surface = (vel_inst_orbita * (rBody/1000)) / (raggioorbita)

        #vel on ground =  vel in orbita * raggioplan / raggioorbita

        mom1string = (f' Primo momento disponibile: {sp.timout(result4[ntime],tdbfmt)} {result4[ntime]}) \n Emission: {np.rad2deg(emissn)} '
              f'\n Rectangular coordinates: {spoint})'
              f'\n Central point coordinates: Long {"%.3f" % (lon)}° Lat {"%.3f" % (lat)}° '
              f'\n Sub Spacecraft coordinates: Long {"%.3f" % lonsubspace}° Lat {"%.3f" % latsubspace}°'
              f'\n Ground Resolution: {"%.2f" % risoluzione} m \n Flight altitude: {"%.2f" % quota_volo} km'
              f'\n Orbital Velocity [km/s]: {vel_inst_orbita}'
              f'\n Velocity on ground [km/s]: {vel_inst_surface}')

        print(mom1string)

        risposta = input("Uso questa? (y/n)")
        ntime +=1
        if risposta != "n":
            break

    circonf = 2 * np.pi * rBody
    risoluzioneDegLong = (360 / (circonf * np.cos(slat))) * risoluzione

    maxoverlap_px = (maxoverlap/100) * pixel_acrosstrack
    minlong2 = lon + (maxoverlap_px * risoluzioneDegLong * longdirection)

    minoverlap_px = (minoverlap / 100) * pixel_acrosstrack
    maxlong2 = lon + (minoverlap_px * risoluzioneDegLong * longdirection)

    print(risoluzioneDegLong)


    # INIZIO SECONDA RICERCA
    #___________________________________________

    if minlong2 > maxlong2:
        a = minlong2
        minlong2 = maxlong2
        maxlong2 = a

    minlongrad = np.deg2rad(minlong2)
    maxlongrad = np.deg2rad(maxlong2)

    t0 = t0 - 86400
    cnfine = sp.stypes.SPICEDOUBLE_CELL(2)
    sp.wninsd(t0, tf, cnfine)

    dref = camera

    (result1) = sp.gfsntc(target, target_frame, method, abcorr, observer, dref, dvec, crdsys, 'LATITUDE', ">",
                          minlatrad, adjust, step, nintvls, cnfine)
    # tipo = sp.gfsntc(target, target_frame, method, 'LT+S', observer, frame , dvec=bsight, adjust=0, nintvls=500, crdsys="GEODETIC", coord="LATITUDE", relate=">", refval=np.deg2rad(latitudemax), step=30, cnfine=window)

    winsiz = sp.wncard(result1)
    # print(winsiz)

    (result2) = sp.gfsntc(target, target_frame, method, abcorr, observer, dref, dvec, crdsys, 'LATITUDE', "<",
                          maxlatrad, adjust, step, nintvls, result1)
    winsiz = sp.wncard(result2)
    # print(winsiz)

    (result3) = sp.gfsntc(target, target_frame, method, abcorr, observer, dref, dvec, crdsys, 'LONGITUDE', ">",
                          minlongrad, adjust, step, nintvls, result2)
    winsiz = sp.wncard(result3)
    # print(winsiz)

    (result4) = sp.gfsntc(target, target_frame, method, abcorr, observer, dref, dvec, crdsys, 'LONGITUDE', "<",
                          maxlongrad, adjust, step, nintvls, result3)
    winsiz = sp.wncard(result4)
    # print(winsiz)

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
        print(srfvec)
        (trgepc_ILLUM, srfvec_ILLUM, phase_ILLUM, solar_ILLUM, emissn, visiblef_ILLUM, iluminatedf_ILLUM) = sp.illumf(
            method,
            target,
            'SUN', et,
            target_frame,
            'LT+S',
            observer,
            spoint)
        # EMISSION
        (srad, slon, slat) = sp.reclat(spoint)
        lon = slon * sp.dpr()
        lat = slat * sp.dpr()

        pos_camera = sp.spkpos(observer, et, target_frame, 'NONE', target)[0]
        (r, sslon, sslat) = sp.reclat(pos_camera)
        latsubspace = sslat * 180 / np.pi
        lonsubspace = sslon * 180 / np.pi

        quota_volo = r - (rBody / 1000)
        quota_volo_m = quota_volo * 1000

        squared_dist = np.sum((pos_camera - spoint) ** 2, axis=0)
        dist = np.sqrt(squared_dist) * 1000
        risoluzione = (dist * dimensione_pixel_sul_sensore) / focal
        risoluzione = ((dist / quota_volo_m) * (np.cos(emissn))) * risoluzione
        # risoluzione = (quota_volo_m * dimensione_pixel_sul_sensore) / focal

        obsCode = sp.bodn2c(observer)
        trgCode = sp.bodn2c(target)

        state, onewaylighttime = sp.spkez(obsCode, et, "J2000", 'NONE', trgCode)

        raggioorbita = (onewaylighttime * sp.clight())  # km
        # print(state * 3600)

        velx, vely, velz = state[3:]

        vel_inst_orbita = np.sqrt((velx ** 2) + (vely ** 2) + (velz ** 2))  # km/s

        vel_inst_surface = (vel_inst_orbita * (rBody / 1000)) / (raggioorbita)

        # vel on ground =  vel in orbita * raggioplan / raggioorbita

        mom2string = (
            f' Primo momento disponibile: {sp.timout(result4[ntime], tdbfmt)} {result4[ntime]}) \n Emission: {np.rad2deg(emissn)} '
            f'\n Rectangular coordinates: {spoint})'
            f'\n Central point coordinates: Long {"%.3f" % (lon)}° Lat {"%.3f" % (lat)}° '
            f'\n Sub Spacecraft coordinates: Long {"%.3f" % lonsubspace}° Lat {"%.3f" % latsubspace}°'
            f'\n Ground Resolution: {"%.2f" % risoluzione} m \n Flight altitude: {"%.2f" % quota_volo} km'
            f'\n Orbital Velocity [km/s]: {vel_inst_orbita}'
            f'\n Velocity on ground [km/s]: {vel_inst_surface}')

        print(mom2string)

        risposta = input("Uso questa? (y/n)")
        ntime += 1
        if risposta != "n":
            break

    mom1string = mom1string.replace("Primo momento disponibile:", f"\n {camera} OBSERVATION 1:\n")
    mom2string = mom2string.replace("Primo momento disponibile:", f"\n___________________________\n {camera} OBSERVATION 2:\n")
    print(mom1string,mom2string)



    sp.kclear()



if __name__ == '__main__':
    path2meta = 'data/kernels/bc_plan.tm'
    camera = 'MPO_SIMBIO-SYS_STC-L_F550'  # 'MPO_SIMBIO-SYS_STC-H_P700 & MPO_SIMBIO-SYS_STC-L_P700' & MPO_SIMBIO-SYS_HRIC_FPAN
    dvec = [0, 0, 1]
    observer = 'MPO'
    target = 'MERCURY'
    target_frame = 'IAU_MERCURY'
    method = 'Ellipsoid'
    rBody = 2439400  # m
    step = 10  #espresso in secondi
    minlat = 75
    maxlat = 76
    minlong = 79  # -179+179 per evitare rounding errors in 180
    maxlong = 80
    t0 = '2026 jul 2 18:00:00'
    tf = '2026 jul 5 17:28:38'

    pixel_acrosstrack = 896 # STC 896  HRIC 2048
    longdirection = 1 # longitudine maggiore 1, minore -1
    minoverlap = 40
    maxoverlap = 60 #

    # Data "2026 mar 14 18:00:00" inizio fase operativa
    # Data "2027 may 1 17:00:00"
    # Periodo orbita in secondi


    timefinderAcTrOrbits(path2meta, camera, dvec, observer, target, target_frame, method, rBody, step, minlat, maxlat, minlong, maxlong, t0, tf, longdirection, minoverlap, maxoverlap, pixel_acrosstrack)
