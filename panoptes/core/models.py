
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.db import models
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _

from panoptes.core.model_fields import MACAddressField, TimeZoneField
import panoptes.settings as _settings

from autoslug import AutoSlugField

import datetime

class LocationManager(models.Manager):
	"""Custom manager for the Location model."""

	def get_default(self):
		"""Return the default Location instance."""

		locations = self.all().order_by('name')
		try:
			return self.get(default=True)
		except MultipleObjectsReturned:
			locations.update(default=False)
		except ObjectDoesNotExist:
			pass

		#  Make the first location (sorted by name) be the default if one
		#  exists, otherwise return no location
		try:
			location = locations[0]
		except IndexError:
			return None
		else:
			location.default=True
			location.save()
			return location

class Location(models.Model):
	"""A location with computers whose usage can be tracked."""

	objects          = LocationManager()

	name             = models.CharField(max_length=100, verbose_name=_("name"))
	slug             = AutoSlugField(max_length=100, populate_from="name", verbose_name=_("slug"), unique=True)
	earliest_opening = models.TimeField(verbose_name=_("opens at"))
	latest_closing   = models.TimeField(verbose_name=_("closes at"))
	timezone         = TimeZoneField(verbose_name=_("time zone"))
	default          = models.BooleanField(verbose_name=_("default location"), default=False)

	class Meta:

		app_label = "panoptes"
		verbose_name = _("location")
		verbose_name_plural = _("locations")

	def __unicode__(self):
		return self.name

	@property
	def open_workstation_count(self):
		"""The number of currently available workstations."""
		return self.total_workstation_count - Session.objects.open_for_location(self).count()

	@property
	def total_workstation_count(self):
		"""The total number of workstations at the location."""
		return self.workstations.filter(track=True).count()

class LayoutRowManager(models.Manager):
	"""Custom manager for the LayoutRow model."""

	def overlaid_rows(self, location, overlay):
		"""
		Return a list whose length is equal to the number of LayoutRow instances
		for the Location instance `location` that contains lists of LayoutCell
		objects ordered by their user-defined order with an extra `overlay`
		attribute defining the overlaid data.

		Arguments:
		location -- a Location instance
		overlay -- a Plot instance mapping workstations to some value

		"""

		#  If an overlay is defined, extend each workstation's data to include
		#  an intensity value defining the percentage of the data relative to
		#  the maximum value
		new_overlay = {}
		if overlay:
			for data in overlay:
				if data.y_value:
					cell_overlay = {'data': data.y_label, 'intensity': data.y_percent}
				else:
					cell_overlay = {}
				new_overlay[data.x_value] = cell_overlay
		return [row._make_cell_iterator(new_overlay) for row
				in self.filter(location=location).order_by('order')]

class LayoutRow(models.Model):
	"""One row of a layout."""

	objects  = LayoutRowManager()

	location = models.ForeignKey(Location, verbose_name=_("location"), related_name="layout_rows")
	order    = models.PositiveSmallIntegerField(verbose_name=_("order"))

	class Meta:

		app_label = "panoptes"
		verbose_name = _("location layout row")
		verbose_name_plural = _("location layout rows")

	def __unicode__(self):
		return _("%(location)s row %(row)d") % {
			'location': self.location.name,
			'row': self.order
		}

	def _make_cell_iterator(self, overlay):
		"""
		Return an iterator of all LayoutCell instances associated with this
		row, with an extra `overlay` attribute on each cell that is a dict with
		a `data` key whose value is the data to show for a workstation, and an
		`intensity` key whose value is an integer from 0 to 100 that defines the
		percentage of the data relative to all the overlaid values.
		"""

		for cell in LayoutCell.objects.all_for_row(self):
			try:
				cell_overlay = overlay.get(cell.workstation, None)
			except AttributeError:
				cell_overlay = None
			cell.overlay = cell_overlay
			yield cell

	def human_order(self):
		"""Return the 1-indexed order."""
		return self.order + 1
	human_order.short_description = _("row number")
	human_order.admin_order_field = 'order'

class LayoutCellManager(models.Manager):
	"""Custom manager for the LayoutCell model."""

	def all_for_row(self, row):
		"""Return all cells for a given row, ordered by the user-defined order."""
		return self.select_related('workstation').filter(row=row).order_by('order')

class LayoutCell(models.Model):
	"""A single cell in a layout row."""

	objects = LayoutCellManager()

	row         = models.ForeignKey(LayoutRow, verbose_name=_("row"), related_name="cells")
	workstation = models.ForeignKey('Workstation', verbose_name=_("workstation"), blank=True, null=True)
	order       = models.PositiveSmallIntegerField(verbose_name=_("order"))

	class Meta:

		app_label = "panoptes"
		verbose_name = _("location layout cell")
		verbose_name_plural = _("location layout cells")

	def __unicode__(self):
		return _("%(row)s cell %(cell)d") % {
			'cell': self.order,
			'row': self.row
		}

	@property
	def is_workstation(self):
		"""True if the cell is a Workstation instance."""
		return self.workstation is not None

	def human_order(self):
		"""Return the 1-indexed order."""
		return self.order + 1
	human_order.short_description = _("cell number")
	human_order.admin_order_field = 'order'

class WorkstationManager(models.Manager):
	"""Custom manager for the Workstation model."""

	def all_for_location(self, location):
		"""Return all workstations for a location, ordered by name.

		Arguments:
		location -- a Location instance

		Returns: a queryset of Workstation instances

		"""
		return self.filter(location=location, track=True).order_by('name')

	def trackable_by_mac(self, mac_address):
		"""Return the trackable workstation with the given MAC address.

		Arguments:
		mac_address -- a string of a workstation's MAC adress

		Returns: a single Workstation instance or None
		"""
		try:
			return MACAddress.objects.get(address=mac_address, workstation__track=True).workstation
		except MACAddress.DoesNotExist:
			return None

class Workstation(models.Model):
	"""A workstation at a location, identified by its MAC address."""

	objects = WorkstationManager()

	name     = models.CharField(max_length=50, verbose_name=_("name"))
	location = models.ForeignKey(Location, verbose_name=_("location"), related_name="workstations")
	track    = models.BooleanField(verbose_name=_("track usage?"), default=True)

	class Meta:

		app_label = "panoptes"
		verbose_name = _("workstation")
		verbose_name_plural = _("workstations")

	def __unicode__(self):
		return self.name

class MACAddress(models.Model):
	"""A MAC address for a NIC on a workstation."""

	NIC_CHOICES = (
		("ethernet", _("ethernet")),
		("wireless", _("wireless")),
		("other", _("other"))
	)

	workstation = models.ForeignKey(Workstation, verbose_name=_("workstation"), related_name="mac_addresses")
	address     = MACAddressField(verbose_name=_("MAC address"), unique=True)
	nic         = models.CharField(choices=NIC_CHOICES, max_length=25, verbose_name=_("NIC type"))

	class Meta:

		app_label = "panoptes"
		verbose_name = _("MAC address")
		verbose_name_plural = _("MAC addresses")

	def __unicode__(self):
		return self.address

	def address_with_separators(self, separator=":"):
		"""Provide the MAC address with the given separator between each pair.

		:param separator: the separator to use between each hexadecimal pair
		:type separator: str

		"""
		address = self.address
		return separator.join([address[i:i+2] for i in xrange(0, len(address), 2)])

class OSTypeManager(models.Manager):
	"""Custom manager for the OSType model."""

	def get_or_create(self, name, version):
		"""Return an OSType type instance matching the passed parameters.

		This will create a new OSType instance if none exists matching the passed
		values, provided that at least `name` is not None.
		"""
		name = name or None
		version = version or None
		try:
			return self.get(name=name, version=version)
		except OSType.DoesNotExist:
			try:
				return self.create(name=name, version=version)
			except ValueError:
				return None

class OSType(models.Model):
	"""An operating system that a machine can run."""

	objects = OSTypeManager()

	name    = models.CharField(max_length=20, choices=_settings.OS_CHOICES, verbose_name=_("operating system"))
	version = models.CharField(max_length=20, verbose_name=_("version"), null=True, blank=True)

	class Meta:

		app_label = "panoptes"
		verbose_name = _("OS type")
		verbose_name_plural = _("OS types")

	def __unicode__(self):
		return u" ".join([self.name, self.version or u""])

class SessionManager(models.Manager):
	"""Custom manager for the Session model."""

	def start_session(self, workstation, os_instance):
		"""Create a new session for the given workstation.

		If an error occurs during the creation of the session, None is returned and
		the session is not tracked.

		Arguments:
		workstation -- a Workstation instance
		os_instance -- an instance of an OSType model

		Returns: a new Session instance
		"""

		#  Clear any unclosed sessions before opening a new one
		if workstation and os_instance:
			self.filter(workstation=workstation, end__isnull=True).delete()
			return self.create(workstation=workstation, os_type=os_instance)
		else:
			return None

	def end_session(self, workstation, apps_used=[], time_offset=0):
		"""Finalize the session associated with the workstation.

		If the workstation is valid and the session was properly closed, the Session
		instance is returned.  If the session could not be closed, None is given.

		The `apps_used` argument is a list of two-tuples of the form
		(reported_app_name, duration), with the duration expressed as an integer of
		the number of seconds of the app usage's length.

		The `time_offset` argument is an optional number of seconds, either
		positive or negative, to apply to the end time recorded for the session.
		This can be used to decrease the session length if the end is occurring
		due to an automatic idle logout, for example.

		Arguments:

		workstation -- a Workstation instance
		apps_used -- a list of apps used
		time_offset -- an integer of the number of seconds to add to the end time

		Returns: a Session instance on success or None on failure

		"""

		#  Close the most recent unclosed session, applying the time offset if
		#  needed and performing a sanity check to prevent sessions with an end
		#  time less than their start time
		try:
			session = self.filter(workstation=workstation, end__isnull=True).order_by('-end')[0]
		except IndexError:
			return None
		else:

			#  Set the session's ending time if it occurs after the start time
			end = datetime.datetime.now()
			if time_offset != 0:
				end += datetime.timedelta(seconds=time_offset)
			if session.start >= end:
				session.delete()
				return None
			session.end = end
			session.end_date = end.date()
			session.end_time = end.time()
			session.save()

			#  If any application usage records exist, create instances for them
			for app in apps_used:
				session.add_app_usage(*app)

			return session

	def filter_sessions(self, location=None, start_date=None, end_date=None, start_time=None, end_time=None, weekdays=[], related_fields=[]):
		"""
		Return a queryset of Session instances based upon the given date
		filters, ordered by the session's start date and time.

		The `start_date` and `end_date` kwargs should be either date or datetime
		instances, the `start_time` and `end_time` kwargs should be time
		instances, and the `weekdays` kwarg should be a list of numbers
		representing weekdays to filter by, following the ISO weekday system,
		with Monday as 1 and Sunday as 7.

		This also accepts a `related_fields` kwarg specifying a list of names of
		model fields to follow.
		"""
		queries = self.create_q_objects(
			location=location,
			start_date=start_date,
			end_date=end_date,
			start_time=start_time,
			end_time=end_time,
			weekdays=weekdays
		)
		queryset = self.filter(*queries).order_by("start")
		if related_fields:
			queryset = queryset.select_related(*related_fields)
		return queryset

	def create_q_objects(self, related_prefix=None, location=None, start_date=None, end_date=None, start_time=None, end_time=None, weekdays=[]):
		"""
		Generate a list of Q objects to use as an argument to a `filter` call on a
		queryset manager.  The optional `related_prefix` kwarg can be the name of a
		field on a model that has a related field of a Session.
		"""

		queries = [
			self._make_q('workstation__track', True, related_prefix)
		]

		if location:
			queries.append(self._make_q('workstation__location', location, related_prefix))
		if start_date:
			queries.append(self._make_q('start_date__gte', start_date, related_prefix))
		if end_date:
			queries.append(self._make_q('end_date__lte', end_date, related_prefix))
		if start_time:
			queries.append(self._make_q('start_time__gte', start_time, related_prefix))
		if end_time:
			queries.append(self._make_q('end_time__lte', end_time, related_prefix))

		if weekdays:
			days = None
			for weekday in weekdays:
				q_key = 'start__week_day'
				if related_prefix:
					q_key = "%s__%s" % (related_prefix, q_key)
				day_args = {q_key: weekday % 7 + 1}
				if not days:
					days = Q(**day_args)
				else:
					days |= Q(**day_args)
			queries.append(days)

		return queries

	def _make_q(self, query, val, prefix=None):
		"""Return a Q object describing the given query.

		Arguments:
		query -- a string that will be the left-hand side of a Q object kwarg
		val -- an object that will be the right-hand side of a Q object kwarg
		prefix -- an optional kwarg that will be used as a related-field prefix

		Returns: a Q object

		"""
		if prefix:
			query = "%s__%s" % (prefix, query)
		return Q(**{query: val})

	def first_session_date_for_location(self, location):
		"""Return a date instance of the location's first recorded session.

		Arguments:
		location -- a Location instance

		Returns:
		A date instance for the first session's date

		"""
		first_session = self.filter(workstation__location=location).order_by('-start_date')[:1]
		try:
			return first_session[0]
		except IndexError:
			return None

	def open_for_location(self, location):
		"""Return a queryset of open sessions at the given location."""
		return self.filter(workstation__track=True, workstation__location=location, end__isnull=True)

	def active_session_for_workstation(self, workstation):
		"""Get a possible active session for the workstation.

		:param workstation: a workstation that might have an active session
		:type workstation: Workstation
		:returns: an active session for the workstation or None
		:rtype: Session or None

		"""
		try:
			return self.filter(workstation=workstation, end__isnull=True).order_by('-start_date')[0]
		except IndexError:
			return None

class Session(models.Model):
	"""A record of a workstation's usage."""

	objects     = SessionManager()

	workstation = models.ForeignKey(Workstation, verbose_name=_("workstation"))
	start       = models.DateTimeField(auto_now_add=True, verbose_name=_("session start"))
	start_date  = models.DateField(auto_now_add=True, verbose_name=_("session start date"))
	start_time  = models.TimeField(auto_now_add=True, verbose_name=_("session start time"))
	end         = models.DateTimeField(blank=True, null=True, verbose_name=_("session end"))
	end_date    = models.DateField(blank=True, null=True, verbose_name=_("session end date"))
	end_time    = models.TimeField(blank=True, null=True, verbose_name=_("session end time"))
	os_type     = models.ForeignKey(OSType, verbose_name=_("operating system"))

	class Meta:

		app_label = "panoptes"
		verbose_name = _("session")
		verbose_name_plural = _("sessions")

	def __unicode__(self):
		return self.workstation.__unicode__()

	def add_app_usage(self, reported_name, duration):
		"""Associate an application usage with the current session.

		Arguments:
		reported_name -- the name used to report the application
		duration -- a value in seconds indicating the duration of usage

		"""
		ApplicationUse.objects.log_usage(self, reported_name, duration)

class Application(models.Model):
	"""
	An application used on a workstation.

	This model, in contrast to the ReportedApplication model, acts as a way to
	normalize the reported application names to one single, useful application.
	For example, PowerPoint might be reported as either "Microsoft PowerPoint"
	or "PowerPoint", even though both of them refer to the same application. To
	make this so in Django, a pair of ReportedApplication instances would be
	created that both point to an Application instance.
	"""

	name = models.CharField(max_length=50, verbose_name=_("name"))

	class Meta:

		app_label = "panoptes"
		verbose_name = _("application")
		verbose_name_plural = _("applications")

	def __unicode__(self):
		return self.name

class ReportedApplication(models.Model):
	"""
	The name under which the use of an application can be reported.

	This is used in conjuction with the Application model to aggregate different
	reported versions of the same application.
	"""

	name        = models.CharField(max_length=50, verbose_name=_("reported name"))
	application = models.ForeignKey(Application, verbose_name=_("application"))
	location    = models.ForeignKey(Location, verbose_name=_("location"))

	class Meta:

		app_label = "panoptes"
		verbose_name = _("reported application")
		verbose_name_plural = _("reported applications")

	def __unicode__(self):
		return self.name

class ApplicationUseManager(models.Manager):
	"""Custom manager for the ApplicationUse model."""

	def all_for_filters(self, location=None, start_date=None, end_date=None, start_time=None, end_time=None, weekdays=[]):
		"""
		Return a queryset of all application uses for any session that occurred during
		the given date and time bounds.
		"""
		q_filters = Session.objects.create_q_objects(
			related_prefix="session",
			location=location,
			start_date=start_date,
			end_date=end_date,
			start_time=start_time,
			end_time=end_time,
			weekdays=weekdays
		)
		return self.filter(*q_filters)

	def log_usage(self, session, reported_name, duration):
		"""Associate a usage of an application with a session.

		If the reported application name does not map to an Application
		instance, no record of the usage will be created.

		If a usage of the given app already exists for the session, the passed
		duration is used to update the duration of the existing app usage record.

		Arguments:
		session -- a valid Session instance
		reported_name -- a string of the name used to report the application
		duration -- an integer of the number of seconds the app was used for
		"""

		try:
			application = ReportedApplication.objects.get(name=reported_name, location=session.workstation.location).application
		except ReportedApplication.DoesNotExist:
			return None
		else:
			try:
				usage = self.get(session=session, application=application)
			except ApplicationUse.DoesNotExist:
				self.create(application=application, session=session, duration=duration)
			else:
				usage.duration += duration
				usage.save()

class ApplicationUse(models.Model):
	"""
	A record of an application used during a session that can hold information
	on the duration of the session, if these data are provided.
	"""

	objects     = ApplicationUseManager()

	application = models.ForeignKey(Application,verbose_name=_("application"))
	session     = models.ForeignKey(Session, verbose_name=_("session"), related_name="apps_used")
	duration    = models.PositiveIntegerField(verbose_name=_("duration"), default=0)

	class Meta:

		app_label = "panoptes"
		verbose_name = _("application use")
		verbose_name_plural = _("application use")

	def __unicode__(self):
		return self.application.__unicode__()
